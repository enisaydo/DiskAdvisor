from app.collector.collect_metrics import store_points, upsert_rhel_hosts
from app.db.models import Host
from app.services.dynatrace_client import DiskUsagePoint, RhelHost


def test_upsert_rhel_hosts_creates_and_updates(db_session):
    hosts_by_entity_id = upsert_rhel_hosts(
        db_session, [RhelHost(entity_id="HOST-1", hostname="app01", os_version="Red Hat Enterprise Linux 8.6")]
    )
    assert hosts_by_entity_id["HOST-1"].hostname == "app01"
    assert db_session.query(Host).count() == 1

    # Same entity_id, renamed in Dynatrace -> updates in place, no duplicate row.
    hosts_by_entity_id = upsert_rhel_hosts(
        db_session, [RhelHost(entity_id="HOST-1", hostname="app01-renamed", os_version="Red Hat Enterprise Linux 8.6")]
    )
    assert hosts_by_entity_id["HOST-1"].hostname == "app01-renamed"
    assert db_session.query(Host).count() == 1


def test_store_points_writes_only_known_hosts(db_session):
    hosts_by_entity_id = upsert_rhel_hosts(db_session, [RhelHost(entity_id="HOST-1", hostname="app01")])

    points = [
        DiskUsagePoint(
            entity_id="HOST-1",
            mount_point="/var",
            timestamp_ms=1700000000000,
            used_pct=80.0,
            used_bytes=80 * 1024 ** 3,
            capacity_bytes=100 * 1024 ** 3,
        ),
        # Not one of the upserted RHEL hosts -- must not be written.
        DiskUsagePoint(
            entity_id="HOST-UNKNOWN",
            mount_point="/var",
            timestamp_ms=1700000000000,
            used_pct=50.0,
            used_bytes=50 * 1024 ** 3,
            capacity_bytes=100 * 1024 ** 3,
        ),
        # No derived bytes -- must be skipped.
        DiskUsagePoint(entity_id="HOST-1", mount_point="/", timestamp_ms=1700000000000, used_pct=10.0),
    ]

    written = store_points(db_session, points, hosts_by_entity_id)

    assert written == 1
    assert hosts_by_entity_id["HOST-1"].disk_metrics[0].mount_point == "/var"
