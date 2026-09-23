"""Entrypoint for the diskadvisor-collector systemd timer/oneshot service.

Three-step pull from Dynatrace, every run:
  1. Discover every RHEL host entity (Entities API v2) and upsert it into
     `hosts` (by dt_entity_id) -- this is the fleet inventory, kept in sync
     as hosts are added/decommissioned in Dynatrace.
  2. Discover every disk entity fleet-wide (Entities API v2, `list_all_disks`)
     to build a disk_entity_id -> real mount path map. This is the
     authoritative source for mount points: the Metrics API response's own
     `mountPoint` dimension text was observed missing/unreliable on a live
     Managed tenant, which silently merged different filesystems on the same
     host together (e.g. `/` and `/var/log/audit` both collapsing into one
     bucket, producing nonsensical combined usage like "200% used").
  3. Query usedPct + availableBytes (Metrics API v2) scoped to exactly the
     RHEL host entity IDs, resolve each point's mount path via the disk map,
     and append the resulting per-disk samples to disk_metrics. Points whose
     disk entity has no resolvable mount point are skipped and counted
     (logged), never silently mislabeled.

Idempotent-ish: it simply appends new samples, matching the collector's
periodic nature; growth trend is later derived from windowed queries over
this table.

Run manually with: python -m app.collector.collect_metrics
"""
from __future__ import annotations

import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import DiskMetric, Host
from app.db.session import SessionLocal
from app.services.dynatrace_client import DiskEntity, DynatraceClient, DiskUsagePoint, RhelHost

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("diskadvisor.collector")


def upsert_rhel_hosts(db: Session, rhel_hosts: list[RhelHost]) -> dict[str, Host]:
    """Inserts/updates `hosts` rows for the given Dynatrace RHEL host
    entities, keyed by `dt_entity_id`. Returns a dt_entity_id -> Host map
    so the caller can attach disk_metrics rows without a second query.
    """
    by_entity_id: dict[str, Host] = {}
    for rhel_host in rhel_hosts:
        host = db.execute(
            select(Host).where(Host.dt_entity_id == rhel_host.entity_id)
        ).scalar_one_or_none()
        if host is None:
            host = Host(dt_entity_id=rhel_host.entity_id, hostname=rhel_host.hostname)
            db.add(host)
        elif host.hostname != rhel_host.hostname:
            host.hostname = rhel_host.hostname
        by_entity_id[rhel_host.entity_id] = host
    db.commit()
    for host in by_entity_id.values():
        db.refresh(host)
    return by_entity_id


def build_mount_point_map(disks: list[DiskEntity]) -> dict[str, str]:
    """disk_entity_id -> real mount path, from the fleet-wide Entities API
    scan. This is what `store_points` uses to label each metric sample --
    never the metric response's own (unreliable, tenant-dependent)
    `mountPoint` dimension text."""
    return {disk.entity_id: disk.mount_point for disk in disks}


def store_points(
    db: Session,
    points: list[DiskUsagePoint],
    hosts_by_entity_id: dict[str, Host],
    mount_point_by_disk_id: dict[str, str] | None = None,
) -> tuple[int, int]:
    """Returns (written, skipped_unresolved_mount)."""
    mount_point_by_disk_id = mount_point_by_disk_id or {}
    written = 0
    skipped_unresolved = 0
    for point in points:
        if point.capacity_bytes is None or point.used_bytes is None:
            # usedPct/availableBytes pair had no overlapping sample for this
            # (host, disk, timestamp) -- nothing to derive bytes from yet.
            continue
        host = hosts_by_entity_id.get(point.entity_id)
        if host is None:
            # Defensive: query_disk_usage was scoped to RHEL entity_ids, so
            # this should not happen outside of tests with ad-hoc points.
            continue

        mount_point = (
            mount_point_by_disk_id.get(point.disk_entity_id) if point.disk_entity_id else None
        ) or point.mount_point
        if not mount_point:
            # Neither the Entities API disk map nor the metric response's own
            # dimension gave a usable mount path -- skip rather than guess
            # (guessing "/" is exactly the bug that caused unrelated
            # filesystems to collide into one row).
            skipped_unresolved += 1
            continue

        metric = DiskMetric(
            host_id=host.id,
            mount_point=mount_point,
            capacity_bytes=point.capacity_bytes,
            used_bytes=point.used_bytes,
            used_pct=point.used_pct or (point.used_bytes / point.capacity_bytes * 100.0),
        )
        db.add(metric)
        written += 1
    db.commit()
    return written, skipped_unresolved


def run() -> int:
    settings = get_settings()
    client = DynatraceClient(settings)
    db = SessionLocal()
    try:
        logger.info("Dynatrace'den RHEL host envanteri çekiliyor...")
        rhel_hosts = client.list_rhel_hosts()
        logger.info("%d RHEL host bulundu.", len(rhel_hosts))
        hosts_by_entity_id = upsert_rhel_hosts(db, rhel_hosts)

        if not hosts_by_entity_id:
            logger.warning("Dynatrace'de RHEL host bulunamadı, metrik sorgusu atlanıyor.")
            return 0

        logger.info("Dynatrace'den disk envanteri (mount point eşleştirmesi) çekiliyor...")
        disks = client.list_all_disks()
        mount_point_by_disk_id = build_mount_point_map(disks)
        logger.info("%d disk entity bulundu.", len(disks))

        logger.info("Bu host'lara ait disk kullanım metrikleri çekiliyor...")
        points = client.query_disk_usage(entity_ids=list(hosts_by_entity_id))
        written, skipped_unresolved = store_points(db, points, hosts_by_entity_id, mount_point_by_disk_id)
        logger.info("%d metrik satırı yazıldı, %d nokta mount point çözülemediği için atlandı.", written, skipped_unresolved)
        return 0
    except Exception:
        logger.exception("Metrik toplama başarısız oldu")
        return 1
    finally:
        db.close()
        client.close()


if __name__ == "__main__":
    sys.exit(run())
