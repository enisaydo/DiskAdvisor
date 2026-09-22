"""Helpers to read disk_metrics history for a host/mount and derive growth trend."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DiskMetric
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
