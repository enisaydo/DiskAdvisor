"""One-time disk audit of a host (top directories, growing files, logrotate
config presence), triggered synchronously at request evaluation time by
launching a job template on Ansible Automation Platform (AAP) Controller,
scoped to the single target host via the `limit` parameter. Results are
read back from the TTL cache backed by the `directory_audits` table so
repeated requests for the same host/mount within the TTL window do not
trigger a new Controller job.

DiskAdvisor never runs Ansible locally and never opens an SSH connection
itself -- it is a Controller API client. The Controller's own inventory,
credentials and RBAC govern how the target host is actually reached.

If the audit cannot be performed (job launch failure, job failed on
Controller, timeout waiting for completion), `run_audit` returns None.
Callers MUST treat that as "audit unavailable" and never proceed to a
silent APPROVE (see scoring.py).
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import DirectoryAudit, Host

_TERMINAL_STATUSES = {"successful", "failed", "error", "canceled"}


@dataclass
class AuditResult:
    top_dirs: dict
    growing_files: dict
    logrotate_findings: dict
    reclaimable_bytes: int
    has_logrotate: bool
    source: str  # "ssh" or "cache"


def get_cached_audit(db: Session, host_id: int, mount_point: str, ttl_hours: int) -> DirectoryAudit | None:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=ttl_hours)
    audit = (
        db.query(DirectoryAudit)
        .filter(DirectoryAudit.host_id == host_id, DirectoryAudit.mount_point == mount_point)
        .filter(DirectoryAudit.collected_at >= cutoff)
        .order_by(DirectoryAudit.collected_at.desc())
        .first()
    )
    return audit


def _launch_controller_job(hostname: str, mount_point: str, settings: Settings) -> dict | None:
    """Launches the DiskAdvisor audit job template on AAP Controller, scoped
    to a single host via `limit`, polls until it reaches a terminal status,
    and returns the facts published by the playbook's `set_stats` task
    (surfaced by Controller as the job's `artifacts`).

    POST {base_url}/api/controller/v2/job_templates/{id}/launch/
        {"limit": "<hostname>", "extra_vars": {"target_mount_point": "<mount>"}}
    GET  {base_url}/api/controller/v2/jobs/{job_id}/   (polled for status + artifacts)

    Returns None on any failure: launch error, job failed/error/canceled on
    Controller, or the poll budget (ssh_audit_timeout_seconds) is exhausted
    before the job reaches a terminal status.
    """
    base_url = settings.ansible_controller_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.ansible_controller_token}"}

    with httpx.Client(base_url=base_url, headers=headers, verify=settings.ansible_controller_verify_ssl) as client:
        try:
            launch_resp = client.post(
                f"/api/controller/v2/job_templates/{settings.ansible_controller_job_template_id}/launch/",
                json={
                    "limit": hostname,
                    "extra_vars": {"target_mount_point": mount_point},
                },
                timeout=settings.ssh_audit_timeout_seconds,
            )
            launch_resp.raise_for_status()
            job_id = launch_resp.json()["job"]
        except (httpx.HTTPError, KeyError):
            return None

        deadline = time.monotonic() + settings.ssh_audit_timeout_seconds
        job_payload: dict = {}
        while time.monotonic() < deadline:
            try:
                status_resp = client.get(f"/api/controller/v2/jobs/{job_id}/", timeout=settings.ssh_audit_timeout_seconds)
                status_resp.raise_for_status()
                job_payload = status_resp.json()
            except httpx.HTTPError:
                return None

            if job_payload.get("status") in _TERMINAL_STATUSES:
                break
            time.sleep(settings.ansible_controller_poll_interval_seconds)
        else:
            return None  # poll budget exhausted before a terminal status was reached

        if job_payload.get("status") != "successful":
            return None

        # The playbook publishes results via `ansible.builtin.set_stats`,
        # which Controller surfaces as the job's `artifacts` dict.
        artifacts = job_payload.get("artifacts") or {}
        return artifacts or None


def run_audit(
    db: Session,
    host: Host,
    mount_point: str,
    settings: Settings | None = None,
    launch_fn=_launch_controller_job,
) -> AuditResult | None:
    """Returns cached audit if fresh, otherwise launches a new AAP Controller
    audit job for this host, persists the result to `directory_audits`, and
    returns it. Returns None if the audit could not be performed at all.
    """
    settings = settings or get_settings()

    cached = get_cached_audit(db, host.id, mount_point, settings.ssh_audit_cache_ttl_hours)
    if cached is not None:
        return AuditResult(
            top_dirs=cached.top_dirs_json,
            growing_files=cached.growing_files_json,
            logrotate_findings=cached.logrotate_findings_json,
            reclaimable_bytes=int(cached.logrotate_findings_json.get("reclaimable_bytes", 0)),
            has_logrotate=bool(cached.logrotate_findings_json.get("has_logrotate", False)),
            source="cache",
        )

    facts = launch_fn(host.hostname, mount_point, settings)
    if facts is None:
        return None

    top_dirs = facts.get("top_dirs", {})
    growing_files = facts.get("growing_files", {})
    logrotate_findings = facts.get("logrotate_findings", {})

    audit_row = DirectoryAudit(
        host_id=host.id,
        mount_point=mount_point,
        top_dirs_json=top_dirs,
        growing_files_json=growing_files,
        logrotate_findings_json=logrotate_findings,
        source="ssh",
    )
    db.add(audit_row)
    db.commit()

    return AuditResult(
        top_dirs=top_dirs,
        growing_files=growing_files,
        logrotate_findings=logrotate_findings,
        reclaimable_bytes=int(logrotate_findings.get("reclaimable_bytes", 0)),
        has_logrotate=bool(logrotate_findings.get("has_logrotate", False)),
        source="ssh",
    )
