from unittest.mock import patch

from app.api.routes.hosts import _resolution_for_window
from app.db.models import Host
from app.main import app
from app.services import ssh_audit
from app.services.dynatrace_client import MetricPoint, MetricSeries, get_dynatrace_client


def test_resolution_for_window_scales_with_lookback_days():
    assert _resolution_for_window(1) == "1h"
    assert _resolution_for_window(2) == "1h"
    assert _resolution_for_window(7) == "2h"
    assert _resolution_for_window(14) == "4h"
    assert _resolution_for_window(30) == "1d"


def _fake_audit_available(*args, **kwargs):
    return ssh_audit.AuditResult(
        top_dirs={"/var/log": 30 * 1024 ** 3},
        growing_files={},
        logrotate_findings={"has_logrotate": False, "reclaimable_bytes": 20 * 1024 ** 3},
        reclaimable_bytes=20 * 1024 ** 3,
        has_logrotate=False,
        source="ssh",
    )


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_evaluate_without_metrics_or_audit_is_manual_review(client):
    with patch.object(ssh_audit, "run_audit", return_value=None):
        resp = client.post(
            "/api/v1/advisor/evaluate",
            json={
                "ticket_id": "TCK-1",
                "hostname": "host01.example.com",
                "mount_point": "/var",
                "requested_gb": 20,
                "requester": "enisaydogan39@gmail.com",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "MANUAL_REVIEW"
    assert body["score"] is None


def test_evaluate_with_audit_available_but_no_metrics_stays_safe(client):
    with patch.object(ssh_audit, "run_audit", side_effect=_fake_audit_available):
        resp = client.post(
            "/api/v1/advisor/evaluate",
            json={
                "ticket_id": "TCK-2",
                "hostname": "host02.example.com",
                "mount_point": "/var/log",
                "requested_gb": 30,
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    # No Dynatrace metric history exists for this host yet -> must not
    # silently APPROVE.
    assert body["decision"] == "MANUAL_REVIEW"


def test_list_requests_and_get_request(client):
    with patch.object(ssh_audit, "run_audit", return_value=None):
        create = client.post(
            "/api/v1/advisor/evaluate",
            json={
                "ticket_id": "TCK-3",
                "hostname": "host03.example.com",
                "mount_point": "/data",
                "requested_gb": 10,
            },
        )
    assert create.status_code == 200
    request_id = create.json()["request_id"]

    listing = client.get("/api/v1/requests")
    assert listing.status_code == 200
    assert any(r["id"] == request_id for r in listing.json())

    detail = client.get(f"/api/v1/requests/{request_id}")
    assert detail.status_code == 200
    assert detail.json()["ticket_id"] == "TCK-3"


def test_override_decision(client):
    with patch.object(ssh_audit, "run_audit", return_value=None):
        create = client.post(
            "/api/v1/advisor/evaluate",
            json={
                "ticket_id": "TCK-4",
                "hostname": "host04.example.com",
                "mount_point": "/data",
                "requested_gb": 10,
            },
        )
    request_id = create.json()["request_id"]

    resp = client.post(
        f"/api/v1/requests/{request_id}/override",
        json={"new_decision": "APPROVE", "reason": "Manuel onay verildi", "user": "enisaydogan39@gmail.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["new_decision"] == "APPROVE"


def test_override_invalid_decision_rejected(client):
    with patch.object(ssh_audit, "run_audit", return_value=None):
        create = client.post(
            "/api/v1/advisor/evaluate",
            json={
                "ticket_id": "TCK-5",
                "hostname": "host05.example.com",
                "mount_point": "/data",
                "requested_gb": 10,
            },
        )
    request_id = create.json()["request_id"]

    resp = client.post(
        f"/api/v1/requests/{request_id}/override",
        json={"new_decision": "NOT_A_DECISION", "reason": "x", "user": "u"},
    )
    assert resp.status_code == 400


def test_list_hosts_empty_then_populated(client):
    resp = client.get("/api/v1/hosts")
    assert resp.status_code == 200
    assert resp.json() == []

    with patch.object(ssh_audit, "run_audit", return_value=None):
        client.post(
            "/api/v1/advisor/evaluate",
            json={
                "ticket_id": "TCK-6",
                "hostname": "host06.example.com",
                "mount_point": "/data",
                "requested_gb": 5,
            },
        )

    resp = client.get("/api/v1/hosts")
    assert resp.status_code == 200
    assert any(h["hostname"] == "host06.example.com" for h in resp.json())


def test_host_correlation_without_dt_entity_id_returns_400(client, db_session):
    host = Host(hostname="host07.example.com")
    db_session.add(host)
    db_session.commit()

    resp = client.get("/api/v1/hosts/host07.example.com/correlation")
    assert resp.status_code == 400


def test_host_correlation_returns_labeled_series(client, db_session):
    host = Host(hostname="host08.example.com", dt_entity_id="HOST-XYZ")
    db_session.add(host)
    db_session.commit()

    class FakeDynatraceClient:
        def query_metrics(self, entity_id, metric_selectors, resolution="1h", time_from="-7d"):
            assert entity_id == "HOST-XYZ"
            assert resolution == "2h"  # 7-day window -> 2h resolution, see _resolution_for_window
            return {
                "builtin:host.cpu.usage": MetricSeries(
                    metric_id="builtin:host.cpu.usage",
                    points=[MetricPoint(timestamp_ms=1700000000000, value=42.0)],
                )
            }

    app.dependency_overrides[get_dynatrace_client] = lambda: FakeDynatraceClient()
    try:
        resp = client.get("/api/v1/hosts/host08.example.com/correlation?days=7")
    finally:
        del app.dependency_overrides[get_dynatrace_client]

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["label"] == "CPU kullanımı"
    assert body[0]["unit"] == "%"
    assert body[0]["points"] == [{"timestamp_ms": 1700000000000, "value": 42.0}]
