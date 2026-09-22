"""Entrypoint for the diskadvisor-collector systemd timer/oneshot service.

Two-step pull from Dynatrace, every run:
  1. Discover every RHEL host entity (Entities API v2) and upsert it into
     `hosts` (by dt_entity_id) -- this is the fleet inventory, kept in sync
     as hosts are added/decommissioned in Dynatrace.
  2. Query usedPct + availableBytes (Metrics API v2) scoped to exactly those
     RHEL host entity IDs, and append the resulting per-disk samples to
     disk_metrics. Non-RHEL hosts (Windows, AIX, ...) are never queried.

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
from app.services.dynatrace_client import DynatraceClient, DiskUsagePoint, RhelHost

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


def store_points(db: Session, points: list[DiskUsagePoint], hosts_by_entity_id: dict[str, Host]) -> int:
    written = 0
    for point in points:
        if point.capacity_bytes is None or point.used_bytes is None:
            # usedPct/availableBytes pair had no overlapping sample for this
            # (host, mount, timestamp) -- nothing to derive bytes from yet.
            continue
        host = hosts_by_entity_id.get(point.entity_id)
        if host is None:
            # Defensive: query_disk_usage was scoped to RHEL entity_ids, so
            # this should not happen outside of tests with ad-hoc points.
            continue
        metric = DiskMetric(
            host_id=host.id,
            mount_point=point.mount_point,
            capacity_bytes=point.capacity_bytes,
            used_bytes=point.used_bytes,
            used_pct=point.used_pct or (point.used_bytes / point.capacity_bytes * 100.0),
        )
        db.add(metric)
        written += 1
    db.commit()
    return written


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

        logger.info("Bu host'lara ait disk kullanım metrikleri çekiliyor...")
        points = client.query_disk_usage(entity_ids=list(hosts_by_entity_id))
        written = store_points(db, points, hosts_by_entity_id)
        logger.info("%d metrik satırı yazıldı.", written)
        return 0
    except Exception:
        logger.exception("Metrik toplama başarısız oldu")
        return 1
    finally:
        db.close()
        client.close()


if __name__ == "__main__":
    sys.exit(run())
