from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import CorrelationPointOut, CorrelationSeriesOut, DiskMetricOut, FilesystemGrowthOut, FilesystemUsageOut, HostOut
from app.core.config import get_settings
from app.db.models import DiskMetric, Host
from app.db.session import get_db
from app.services import fleet_analytics
from app.services.dynatrace_client import CORRELATION_METRIC_LABELS, DynatraceClient, get_dynatrace_client

router = APIRouter(prefix="/hosts", tags=["hosts"])


def _resolution_for_window(lookback_days: int) -> str:
    """Scales the Metrics API `resolution` to the requested window so a
    chart never gets flooded with points regardless of how many days are
    selected (e.g. 30 days at fixed 1h resolution would be ~720 points --
    unreadable on a simple line chart). Caps out around 150-200 points."""
    if lookback_days <= 2:
        return "1h"
    if lookback_days <= 7:
        return "2h"
    if lookback_days <= 14:
        return "4h"
    return "1d"


@router.get("", response_model=list[HostOut])
def list_hosts(db: Session = Depends(get_db)):
    return db.execute(select(Host).order_by(Host.hostname)).scalars().all()


@router.get("/top-growth", response_model=list[FilesystemGrowthOut])
def get_top_growth(days: int = 7, limit: int = 10, db: Session = Depends(get_db)):
    """Top N filesystems fleet-wide by used_pct increase over the last
    `days` days (default 7). Ranked by percentage-point growth, not GB,
    so filesystems of very different sizes stay comparable; the GB delta
    is returned alongside for context."""
    return fleet_analytics.top_growing_filesystems(db, days=days, limit=limit)


@router.get("/high-usage", response_model=list[FilesystemUsageOut])
def get_high_usage(threshold_pct: float = 90.0, db: Session = Depends(get_db)):
    """Every filesystem fleet-wide whose latest known usage is at/above
    threshold_pct (default 90%)."""
    return fleet_analytics.high_usage_filesystems(db, threshold_pct=threshold_pct)


@router.get("/{hostname}/metrics", response_model=list[DiskMetricOut])
def get_host_metrics(hostname: str, mount_point: str | None = None, db: Session = Depends(get_db)):
    host = db.execute(select(Host).where(Host.hostname == hostname)).scalar_one_or_none()
    if host is None:
        raise HTTPException(status_code=404, detail="Host bulunamadı")

    stmt = select(DiskMetric).where(DiskMetric.host_id == host.id)
    if mount_point:
        stmt = stmt.where(DiskMetric.mount_point == mount_point)
    stmt = stmt.order_by(DiskMetric.collected_at.asc())
    return db.execute(stmt).scalars().all()


@router.get("/{hostname}/correlation", response_model=list[CorrelationSeriesOut])
def get_host_correlation(
    hostname: str,
    days: int | None = None,
    db: Session = Depends(get_db),
    dt_client: DynatraceClient = Depends(get_dynatrace_client),
):
    """On-demand correlation view for a single host: CPU/memory/network/disk
    I/O over the last `days` days, queried live from Dynatrace (not stored --
    this is for investigating a specific flagged host, e.g. from the
    top-growth list, not a fleet-wide continuous collection). Pair this with
    `/hosts/{hostname}/metrics` (disk usage trend) client-side to see whether
    a resource spike lines up with the disk growth.
    """
    host = db.execute(select(Host).where(Host.hostname == hostname)).scalar_one_or_none()
    if host is None:
        raise HTTPException(status_code=404, detail="Host bulunamadı")
    if not host.dt_entity_id:
        raise HTTPException(
            status_code=400,
            detail="Bu host için Dynatrace entity ID kayıtlı değil (collector henüz senkronize etmemiş olabilir).",
        )

    settings = get_settings()
    lookback_days = days or settings.dynatrace_correlation_lookback_days
    series_by_selector = dt_client.query_metrics(
        entity_id=host.dt_entity_id,
        metric_selectors=settings.dynatrace_correlation_metrics,
        time_from=f"-{lookback_days}d",
        resolution=_resolution_for_window(lookback_days),
    )

    result = []
    for selector, series in series_by_selector.items():
        label, unit = CORRELATION_METRIC_LABELS.get(selector, (selector, ""))
        result.append(
            CorrelationSeriesOut(
                metric_id=series.metric_id,
                label=label,
                unit=unit,
                points=[CorrelationPointOut(timestamp_ms=p.timestamp_ms, value=p.value) for p in series.points],
            )
        )
    return result
