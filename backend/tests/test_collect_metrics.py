from app.collector.collect_metrics import build_mount_point_map, store_points, upsert_rhel_hosts
from app.db.models import Host
from app.services.dynatrace_client import DiskEntity, DiskUsagePoint, RhelHost


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

    written, skipped_unresolved = store_points(db_session, points, hosts_by_entity_id)

    assert written == 1
    assert skipped_unresolved == 0
    assert hosts_by_entity_id["HOST-1"].disk_metrics[0].mount_point == "/var"


def test_store_points_prefers_entities_api_mount_point_over_metric_dimension_text():
    """Regression test for the "%200 used" bug: two different filesystems on
    the same host must never collapse into one mount_point label, even if
    the metric response's own dimension text is missing/wrong. The Entities
    API disk map (disk_entity_id -> real path) must win."""
    hosts_by_entity_id = {"HOST-1": Host(id=1, dt_entity_id="HOST-1", hostname="app01")}
    mount_point_by_disk_id = {
        "DISK-ROOT": "/",
        "DISK-AUDIT": "/var/log/audit",
    }
    points = [
        DiskUsagePoint(
            entity_id="HOST-1",
            mount_point=None,  # metric response gave no usable dimension text
            disk_entity_id="DISK-ROOT",
            timestamp_ms=1700000000000,
            used_pct=53.0,
            used_bytes=int(0.53 * 100 * 1024 ** 3),
            capacity_bytes=100 * 1024 ** 3,
        ),
        DiskUsagePoint(
            entity_id="HOST-1",
            mount_point=None,
            disk_entity_id="DISK-AUDIT",
            timestamp_ms=1700000000000,
            used_pct=100.0,
            used_bytes=2 * 1024 ** 3,
            capacity_bytes=2 * 1024 ** 3,
        ),
    ]

    class FakeDb:
        def __init__(self):
            self.added = []

        def add(self, obj):
            self.added.append(obj)

        def commit(self):
            pass

    db = FakeDb()
    written, skipped_unresolved = store_points(db, points, hosts_by_entity_id, mount_point_by_disk_id)

    assert written == 2
    assert skipped_unresolved == 0
    mount_points = {m.mount_point for m in db.added}
    assert mount_points == {"/", "/var/log/audit"}  # never collapsed into one


def test_store_points_skips_when_mount_point_cannot_be_resolved():
    hosts_by_entity_id = {"HOST-1": Host(id=1, dt_entity_id="HOST-1", hostname="app01")}
    points = [
        DiskUsagePoint(
            entity_id="HOST-1",
            mount_point=None,
            disk_entity_id="DISK-UNKNOWN",  # not in the Entities API map
            timestamp_ms=1700000000000,
            used_pct=50.0,
            used_bytes=50 * 1024 ** 3,
            capacity_bytes=100 * 1024 ** 3,
        ),
    ]

    class FakeDb:
        def add(self, obj):
            raise AssertionError("should not write an unresolved mount point")

        def commit(self):
            pass

    written, skipped_unresolved = store_points(FakeDb(), points, hosts_by_entity_id, mount_point_by_disk_id={})

    assert written == 0
    assert skipped_unresolved == 1


def test_build_mount_point_map():
    disks = [
        DiskEntity(entity_id="DISK-1", mount_point="/var", host_entity_id="HOST-1"),
        DiskEntity(entity_id="DISK-2", mount_point="/", host_entity_id="HOST-1"),
    ]
    assert build_mount_point_map(disks) == {"DISK-1": "/var", "DISK-2": "/"}
