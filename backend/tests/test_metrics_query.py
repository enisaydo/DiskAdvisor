import datetime as dt

from app.db.models import DiskMetric, Host
from app.services.fleet_analytics import GB
from app.services.metrics_query import get_daily_trend


def _add_metric_at(db, host, mount_point, used_pct, collected_at, capacity_gb=100):
    capacity_bytes = capacity_gb * GB
    db.add(
        DiskMetric(
            host_id=host.id,
            mount_point=mount_point,
            capacity_bytes=capacity_bytes,
            used_bytes=int(capacity_bytes * used_pct / 100.0),
            used_pct=used_pct,
            collected_at=collected_at,
        )
    )
    db.flush()


def test_get_daily_trend_collapses_to_one_row_per_day_with_deltas(db_session):
    host = Host(hostname="app01")
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)

    today = dt.datetime.now(dt.timezone.utc)
    two_days_ago = today - dt.timedelta(days=2)
    one_day_ago = today - dt.timedelta(days=1)

    # Two-days-ago: two hourly samples, last one (50%) is the day's anchor.
    _add_metric_at(db_session, host, "/data", used_pct=45.0, collected_at=two_days_ago.replace(hour=1))
    _add_metric_at(db_session, host, "/data", used_pct=50.0, collected_at=two_days_ago.replace(hour=20))
    _add_metric_at(db_session, host, "/data", used_pct=60.0, collected_at=one_day_ago)
    _add_metric_at(db_session, host, "/data", used_pct=63.0, collected_at=today)

    trend = get_daily_trend(db_session, host.id, "/data", days=14)

    assert len(trend) == 3  # one row per distinct calendar day, not per sample
    assert trend[0].used_pct == 50.0
    assert trend[0].growth_pct_points_vs_prev_day is None  # no previous day to compare

    assert trend[1].used_pct == 60.0
    assert trend[1].growth_pct_points_vs_prev_day == 10.0
    assert abs(trend[1].growth_gb_vs_prev_day - 10.0) < 0.01  # 10 points of a 100GB disk

    assert trend[2].used_pct == 63.0
    assert trend[2].growth_pct_points_vs_prev_day == 3.0


def test_get_daily_trend_respects_lookback_window(db_session):
    host = Host(hostname="app02")
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)

    now = dt.datetime.now(dt.timezone.utc)
    _add_metric_at(db_session, host, "/", used_pct=40.0, collected_at=now - dt.timedelta(days=30))
    _add_metric_at(db_session, host, "/", used_pct=50.0, collected_at=now)

    trend = get_daily_trend(db_session, host.id, "/", days=7)

    assert len(trend) == 1  # the 30-day-old sample fell outside the window
    assert trend[0].used_pct == 50.0
