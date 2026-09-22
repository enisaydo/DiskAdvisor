"""Fleet-wide filesystem health views, built directly from the historical
`disk_metrics` collected by diskadvisor-collector. Independent of the
per-request scoring engine: this is for standing up disk usage as a
continuously monitored standard across the whole fleet, not just incoming
tickets.

Growth is ranked by percentage-point change in `used_pct` (e.g. 70% -> 85%
is +15 points), not by absolute GB, because filesystem sizes vary wildly
across the fleet (100 GB vs 2 TB) and a raw GB comparison would just
surface the biggest disks. The absolute GB change is still returned
alongside it so both are visible together, as requested.

Note: for phase-1 this groups in Python over the rows fetched for the
window (top_growing_filesystems) or the whole table (high_usage_filesystems,
which needs each group's single latest row). At 6000 hosts x hourly samples
this is still bounded and fine for now, but if disk_metrics grows large a
later pass should replace this with a windowed SQL query (ROW_NUMBER() /
DISTINCT ON) instead of pulling rows into Python.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DiskMetric, Host

GB = 1024**3


@dataclass
class FilesystemGrowth:
    hostname: str
    mount_point: str
    growth_pct_points: float  # e.g. +15.0 means used_pct went from 70% to 85%
    growth_gb: float
    current_used_pct: float
    current_used_gb: float
    current_capacity_gb: float


@dataclass
class FilesystemUsage:
    hostname: str
    mount_point: str
    used_pct: float
    used_gb: float
    capacity_gb: float
    collected_at: dt.datetime


def _hostnames_by_id(db: Session) -> dict[int, str]:
    return {h.id: h.hostname for h in db.execute(select(Host)).scalars()}


def top_growing_filesystems(db: Session, days: int = 7, limit: int = 10) -> list[FilesystemGrowth]:
    """Top N filesystems by used_pct increase over the last `days` days,
    across the whole fleet (not scoped to any one request)."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    stmt = (
        select(
            DiskMetric.host_id,
            DiskMetric.mount_point,
            DiskMetric.collected_at,
            DiskMetric.used_bytes,
            DiskMetric.used_pct,
            DiskMetric.capacity_bytes,
        )
        .where(DiskMetric.collected_at >= cutoff)
        .order_by(DiskMetric.collected_at.asc())
    )
    rows = db.execute(stmt).all()

    series_by_group: dict[tuple[int, str], list] = {}
    for row in rows:
        series_by_group.setdefault((row.host_id, row.mount_point), []).append(row)

    hostnames = _hostnames_by_id(db)
    results: list[FilesystemGrowth] = []
    for (host_id, mount_point), series in series_by_group.items():
        if len(series) < 2:
            continue  # need at least two samples in the window to measure growth
        earliest, latest = series[0], series[-1]
        results.append(
            FilesystemGrowth(
                hostname=hostnames.get(host_id, f"host-{host_id}"),
                mount_point=mount_point,
                growth_pct_points=round(latest.used_pct - earliest.used_pct, 2),
                growth_gb=round((latest.used_bytes - earliest.used_bytes) / GB, 2),
                current_used_pct=round(latest.used_pct, 2),
                current_used_gb=round(latest.used_bytes / GB, 2),
                current_capacity_gb=round(latest.capacity_bytes / GB, 2),
            )
        )

    results.sort(key=lambda r: r.growth_pct_points, reverse=True)
    return results[:limit]


def high_usage_filesystems(db: Session, threshold_pct: float = 90.0) -> list[FilesystemUsage]:
    """Every filesystem whose *latest known* used_pct is at/above threshold_pct,
    across the whole fleet."""
    stmt = select(DiskMetric).order_by(DiskMetric.collected_at.asc())
    latest_by_group: dict[tuple[int, str], DiskMetric] = {}
    for metric in db.execute(stmt).scalars():
        latest_by_group[(metric.host_id, metric.mount_point)] = metric  # ascending order -> last write wins

    hostnames = _hostnames_by_id(db)
    results = [
        FilesystemUsage(
            hostname=hostnames.get(m.host_id, f"host-{m.host_id}"),
            mount_point=m.mount_point,
            used_pct=round(m.used_pct, 2),
            used_gb=round(m.used_bytes / GB, 2),
            capacity_gb=round(m.capacity_bytes / GB, 2),
            collected_at=m.collected_at,
        )
        for m in latest_by_group.values()
        if m.used_pct >= threshold_pct
    ]
    results.sort(key=lambda r: r.used_pct, reverse=True)
    return results
