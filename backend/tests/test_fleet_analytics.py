import datetime as dt

from app.db.models import DiskMetric, Host
from app.services.fleet_analytics import GB, high_usage_filesystems, top_growing_filesystems


def _add_metric(db, host, mount_point, used_pct, days_ago, capacity_gb=100):
    capacity_bytes = capacity_gb * GB
    db.add(
        DiskMetric(
            host_id=host.id,
            mount_point=mount_point,
            capacity_bytes=capacity_bytes,
            used_bytes=int(capacity_bytes * used_pct / 100.0),
            used_pct=used_pct,
            collected_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago),
        )
    )
    db.flush()  # db_session fixture uses autoflush=False; queries in the code under test need these visible


def test_top_growing_filesystems_ranks_by_pct_points_not_gb(db_session):
    fast = Host(hostname="fast-grower")
    slow = Host(hostname="slow-grower-bigger-disk")
    db_session.add_all([fast, slow])
    db_session.commit()
    db_session.refresh(fast)
    db_session.refresh(slow)

    # fast: 100GB disk, 40% -> 70% in 7 days (+30 points, +30GB)
    _add_metric(db_session, fast, "/var", used_pct=40.0, days_ago=6, capacity_gb=100)
    _add_metric(db_session, fast, "/var", used_pct=70.0, days_ago=0, capacity_gb=100)

    # slow: 2TB disk, 40% -> 45% in 7 days (+5 points, but +100GB absolute -- must NOT outrank fast)
    _add_metric(db_session, slow, "/data", used_pct=40.0, days_ago=6, capacity_gb=2000)
    _add_metric(db_session, slow, "/data", used_pct=45.0, days_ago=0, capacity_gb=2000)

    results = top_growing_filesystems(db_session, days=7, limit=10)

    assert [r.hostname for r in results] == ["fast-grower", "slow-grower-bigger-disk"]
    assert results[0].growth_pct_points == 30.0
    assert results[0].growth_gb == 30.0
    assert results[1].growth_gb == 100.0  # bigger absolute growth, but ranked lower


def test_top_growing_filesystems_skips_single_sample_groups(db_session):
    host = Host(hostname="only-one-sample")
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)

    _add_metric(db_session, host, "/var", used_pct=50.0, days_ago=1)

    assert top_growing_filesystems(db_session, days=7) == []


def test_high_usage_filesystems_filters_and_uses_latest_sample(db_session):
    host = Host(hostname="app01")
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)

    _add_metric(db_session, host, "/var", used_pct=70.0, days_ago=2)  # old sample, should be superseded
    _add_metric(db_session, host, "/var", used_pct=95.0, days_ago=0)  # latest
    _add_metric(db_session, host, "/opt", used_pct=50.0, days_ago=0)  # below threshold

    results = high_usage_filesystems(db_session, threshold_pct=90.0)

    assert len(results) == 1
    assert results[0].mount_point == "/var"
    assert results[0].used_pct == 95.0
