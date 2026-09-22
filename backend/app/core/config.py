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
    # does not give absolute capacity, so availableBytes is used to derive
    # used_bytes/capacity_bytes (capacity = available / (1 - usedPct/100)).
    dynatrace_base_url: str = "https://your-environment.live.dynatrace.com"
    dynatrace_api_token: str = "changeme"
    dynatrace_metric_usedpct_selector: str = "builtin:host.disk.usedPct"
    dynatrace_metric_available_selector: str = "builtin:host.disk.availableBytes"
    dynatrace_timeout_seconds: float = 10.0

    # --- Correlation analysis (on-demand, per suspicious host -- see /hosts/{hostname}/correlation) ---
    # Host-level CPU/memory/network/disk-I/O metrics queried live from Dynatrace
    # when someone opens the Analiz page for a specific host (a top-grower or a
    # host with a live request), never for the whole 6000-host fleet on a timer.
    # IMPORTANT: these metric keys are Dynatrace's documented builtin host
    # metrics but were never verified against a live tenant in this session --
    # confirm they resolve to real data (Metrics API `GET /metrics` browse
    # endpoint) before relying on this, and adjust the list via env if your
    # tenant uses different keys (e.g. an older OneAgent version).
    dynatrace_correlation_metrics: list[str] = [
        "builtin:host.cpu.usage",
        "builtin:host.mem.usage",
        "builtin:host.disk.read.bytes",
        "builtin:host.disk.write.bytes",
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
