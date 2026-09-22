import httpx

from app.core.config import Settings
from app.db.models import Host
from app.services import ssh_audit


def _settings():
    return Settings(ssh_audit_cache_ttl_hours=24)


def test_run_audit_returns_none_when_controller_job_fails(db_session):
    host = Host(hostname="host01")
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)

    def failing_launch(hostname, mount_point, settings):
        return None

    result = ssh_audit.run_audit(db_session, host, "/var", _settings(), launch_fn=failing_launch)
    assert result is None


def test_run_audit_persists_and_caches(db_session):
    host = Host(hostname="host02")
    db_session.add(host)
    db_session.commit()
    db_session.refresh(host)

    calls = {"count": 0, "hostnames": []}

    def fake_launch(hostname, mount_point, settings):
        calls["count"] += 1
        calls["hostnames"].append(hostname)
        return {
            "top_dirs": {"/var/log": 10 * 1024 ** 3},
            "growing_files": {},
            "logrotate_findings": {"has_logrotate": True, "reclaimable_bytes": 5 * 1024 ** 3},
        }

    first = ssh_audit.run_audit(db_session, host, "/var", _settings(), launch_fn=fake_launch)
    assert first is not None
    assert first.source == "ssh"
    assert first.has_logrotate is True
    assert first.reclaimable_bytes == 5 * 1024 ** 3
    assert calls["count"] == 1
    # The job must be scoped to this single host (Controller `limit`).
    assert calls["hostnames"] == ["host02"]

    # Second call within TTL should hit the cache, not launch a new job.
    second = ssh_audit.run_audit(db_session, host, "/var", _settings(), launch_fn=fake_launch)
    assert second is not None
    assert second.source == "cache"
    assert calls["count"] == 1


def test_launch_controller_job_posts_limit_and_extra_vars(monkeypatch):
    """Verifies the real _launch_controller_job POSTs `limit=<hostname>` and
    `extra_vars.target_mount_point`, polls jobs/{id}/, and reads back the
    `set_stats` artifacts -- without touching a real AAP Controller."""
    settings = Settings(
        ansible_controller_base_url="https://aap.example.internal",
        ansible_controller_token="tok",
        ansible_controller_job_template_id=42,
        ansible_controller_poll_interval_seconds=0.0,
        ssh_audit_timeout_seconds=5.0,
    )

    captured = {}

    def handler(request):
        if request.url.path == "/api/controller/v2/job_templates/42/launch/":
            import json as _json

            captured["json"] = _json.loads(request.content)
            return httpx.Response(201, json={"job": 999})
        if request.url.path == "/api/controller/v2/jobs/999/":
            return httpx.Response(
                200,
                json={
                    "status": "successful",
                    "artifacts": {
                        "top_dirs": ["/var/log 123"],
                        "growing_files": [],
                        "logrotate_findings": {"has_logrotate": False, "reclaimable_bytes": 42},
                    },
                },
            )
        raise AssertionError(f"unexpected request: {request.url.path}")

    transport = httpx.MockTransport(handler)
    real_client_cls = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)

    facts = ssh_audit._launch_controller_job("host03", "/var", settings)

    assert captured["json"] == {"limit": "host03", "extra_vars": {"target_mount_point": "/var"}}
    assert facts["logrotate_findings"]["reclaimable_bytes"] == 42
