"""Central configuration, read from environment variables (.env supported)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DISKADVISOR_", env_file=".env", extra="ignore")

    # --- Database (PostgreSQL in every real environment; tests override this) ---
    database_url: str = "postgresql+psycopg2://diskadvisor:diskadvisor@localhost:5432/diskadvisor"

    # --- Dynatrace ---
    # Two builtin per-disk-instance metrics are pulled together in one Metrics
    # API v2 query and merged by (host, mountPoint, timestamp): usedPct alone
    # does not give absolute capacity, so the free-space metric is used to
    # derive used_bytes/capacity_bytes (capacity = available / (1 - usedPct/100)).
    # Verified against a live Dynatrace Managed tenant via
    # `GET /api/v2/metrics?text=disk`: that tenant has `builtin:host.disk.avail`,
    # NOT `builtin:host.disk.availableBytes` (which doesn't exist and made the
    # combined query 404) -- SaaS tenants may differ, always confirm via the
    # browse endpoint above before relying on these defaults.
    dynatrace_base_url: str = "https://your-environment.live.dynatrace.com"
    dynatrace_api_token: str = "changeme"
    dynatrace_metric_usedpct_selector: str = "builtin:host.disk.usedPct"
    dynatrace_metric_available_selector: str = "builtin:host.disk.avail"
    dynatrace_timeout_seconds: float = 10.0
    # False for self-signed/internal-CA Dynatrace Managed or ActiveGate
    # endpoints where the RHEL host doesn't trust the issuing CA. Prefer
    # trusting the CA (update-ca-trust) over this in the long run --
    # disabling verification accepts any certificate, including a forged
    # one from a network-level attacker.
    dynatrace_verify_ssl: bool = True
    # entitySelector's entityId(...) list is chunked to this many hosts per
    # request -- the Metrics API v2 query endpoint is GET-only, and a single
    # request scoped to the whole ~6000-host fleet hits 414 Request-URI Too
    # Large (observed in practice around ~1800 IDs in one URL).
    dynatrace_query_batch_size: int = 100

    # --- Correlation analysis (on-demand, per suspicious host -- see /hosts/{hostname}/correlation) ---
    # Host-level CPU/memory/network/disk-I/O metrics queried live from Dynatrace
    # when someone opens the Analiz page for a specific host (a top-grower or a
    # host with a live request), never for the whole 6000-host fleet on a timer.
    # The two disk I/O keys below were corrected against a live Dynatrace
    # Managed tenant (`GET /api/v2/metrics?text=disk`): the originally
    # guessed `builtin:host.disk.read.bytes`/`write.bytes` don't exist there,
    # the real keys are `builtin:host.disk.bytesRead`/`bytesWritten`.
    # cpu.usage/mem.usage/net.nic.* were NOT in that "disk" browse result and
    # are still unverified -- confirm via `GET /api/v2/metrics?text=cpu` /
    # `?text=network` before relying on them, and adjust via env if your
    # tenant uses different keys (e.g. an older OneAgent version).
    dynatrace_correlation_metrics: list[str] = [
        "builtin:host.cpu.usage",
        "builtin:host.mem.usage",
        "builtin:host.disk.bytesRead",
        "builtin:host.disk.bytesWritten",
        "builtin:host.net.nic.bytesRx",
        "builtin:host.net.nic.bytesTx",
    ]
    dynatrace_correlation_lookback_days: int = 7

    # --- Ansible Automation Platform (AAP) Controller audit job ---
    # DiskAdvisor never touches SSH/inventory directly: it POSTs to Controller's
    # job_templates/{id}/launch/ endpoint with `limit` set to the single target
    # host, and polls jobs/{id}/ for the result. Controller owns the inventory,
    # credentials and RBAC for actually reaching the host.
    ansible_controller_base_url: str = "https://aap-controller.example.internal"
    ansible_controller_token: str = "changeme"
    ansible_controller_job_template_id: int = 0
    ansible_controller_verify_ssl: bool = True
    ansible_controller_poll_interval_seconds: float = 2.0
    ssh_audit_timeout_seconds: float = 30.0
    ssh_audit_cache_ttl_hours: int = 24

    # --- Scoring thresholds (weights, 0-100 scale contributions) ---
    weight_usage_pct: float = 0.35
    weight_growth_trend: float = 0.25
    weight_headroom_days: float = 0.20
    weight_reclaimable: float = 0.20

    # decision thresholds
    threshold_approve: float = 75.0
    threshold_approve_reduced: float = 55.0
    threshold_manual_review: float = 30.0

    # growth trend lookback window for linear regression (days)
    growth_lookback_days: int = 14

    # --- Collector ---
    collector_host_list_source: str = "db"  # "db" | "dynatrace"

    # --- API ---
    api_v1_prefix: str = "/api/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
