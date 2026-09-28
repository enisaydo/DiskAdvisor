"""Helpers to read disk_metrics history for a host/mount and derive growth trend."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DiskMetric
from app.services.fleet_analytics import GB, daily_snapshots
from app.services.scoring import linear_growth_bytes_per_day


def get_latest_metric(db: Session, host_id: int, mount_point: str) -> DiskMetric | None:
    stmt = (
        select(DiskMetric)
        .where(DiskMetric.host_id == host_id, DiskMetric.mount_point == mount_point)
        .order_by(DiskMetric.collected_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def get_growth_bytes_per_day(db: Session, host_id: int, mount_point: str, lookback_days: int) -> float:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days)
    stmt = (
        select(DiskMetric.collected_at, DiskMetric.used_bytes)
        .where(
            DiskMetric.host_id == host_id,
            DiskMetric.mount_point == mount_point,
            DiskMetric.collected_at >= cutoff,
        )
        .order_by(DiskMetric.collected_at.asc())
    )
    rows = db.execute(stmt).all()
    points = [(row[0], row[1]) for row in rows]
    return linear_growth_bytes_per_day(points)


@dataclass
class DailyTrendPoint:
    date: dt.date
    used_pct: float
    used_gb: float
    capacity_gb: float
    growth_pct_points_vs_prev_day: float | None
    growth_gb_vs_prev_day: float | None


def get_daily_trend(db: Session, host_id: int, mount_point: str, days: int = 14) -> list[DailyTrendPoint]:
    """Day-by-day history for one host/mount: one snapshot per calendar day
    (the last sample of that day, see `daily_snapshots`), each with its
    change from the previous day -- "her yeni gün çekilen veri bir önceki
    datalarla karşılaştırılıp büyüme trendi oluşturulacak" for a single
    filesystem someone is drilling into, as opposed to the fleet-wide
    top-growth ranking.
    """
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    stmt = (
        select(DiskMetric)
        .where(
            DiskMetric.host_id == host_id,
            DiskMetric.mount_point == mount_point,
            DiskMetric.collected_at >= cutoff,
        )
        .order_by(DiskMetric.collected_at.asc())
    )
    daily = daily_snapshots(db.execute(stmt).scalars().all())

    result: list[DailyTrendPoint] = []
    prev: DiskMetric | None = None
    for row in daily:
        growth_pct = round(row.used_pct - prev.used_pct, 2) if prev else None
        growth_gb = (
            round((growth_pct / 100.0) * row.capacity_bytes / GB, 2) if prev and growth_pct is not None else None
        )
        result.append(
            DailyTrendPoint(
                date=row.collected_at.date(),
                used_pct=round(row.used_pct, 2),
                used_gb=round(row.used_bytes / GB, 2),
                capacity_gb=round(row.capacity_bytes / GB, 2),
                growth_pct_points_vs_prev_day=growth_pct,
                growth_gb_vs_prev_day=growth_gb,
            )
        )
        prev = row
    return result
