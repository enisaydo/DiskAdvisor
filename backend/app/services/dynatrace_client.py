"""Thin wrapper around Dynatrace Metrics API v2 (query endpoint).

Docs: https://docs.dynatrace.com/docs/dynatrace-api/environment-api/metric-v2/get-data-points

Pulls two builtin per-disk-instance metrics in a single call (comma-joined
metricSelector, one `result` entry per metric in the response) and merges
them by (host entity, mountPoint, timestamp):
  - builtin:host.disk.usedPct       -- % used, per disk/mount, hourly
  - builtin:host.disk.availableBytes -- free bytes, per disk/mount, hourly

usedPct alone has no absolute capacity, so capacity_bytes/used_bytes are
derived from the pair: capacity = available / (1 - usedPct/100).

This is a real HTTP client (httpx), but in this phase it is never called
against a live Dynatrace tenant -- it is exercised only via unit tests with
a mocked transport/response.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings


@dataclass
class DiskUsagePoint:
    entity_id: str
    mount_point: str
    timestamp_ms: int
    used_pct: float | None = None
    used_bytes: int | None = None
    capacity_bytes: int | None = None


@dataclass
class RhelHost:
    """A RHEL host entity from the Dynatrace Entities API."""

    entity_id: str  # e.g. "HOST-ABCDEF0123456789"
    hostname: str
    os_version: str | None = None


@dataclass
class DiskEntity:
    """A disk entity attached to a host, from the Dynatrace Entities API."""

    entity_id: str  # e.g. "DISK-ABCDEF0123456789"
    mount_point: str
    host_entity_id: str


@dataclass
class MetricPoint:
    timestamp_ms: int
    value: float | None


@dataclass
class MetricSeries:
    metric_id: str
    points: list[MetricPoint]


# Human-friendly label/unit for known correlation metrics, used by the API
# layer when rendering /hosts/{hostname}/correlation. A metric selector not
# listed here (e.g. a tenant-specific one added via config) falls back to
# showing the raw selector as its own label.
CORRELATION_METRIC_LABELS: dict[str, tuple[str, str]] = {
    "builtin:host.cpu.usage": ("CPU kullanımı", "%"),
    "builtin:host.mem.usage": ("Bellek kullanımı", "%"),
    "builtin:host.disk.read.bytes": ("Disk okuma", "bytes/s"),
    "builtin:host.disk.write.bytes": ("Disk yazma", "bytes/s"),
    "builtin:host.net.nic.bytesRx": ("Network alınan", "bytes/s"),
    "builtin:host.net.nic.bytesTx": ("Network gönderilen", "bytes/s"),
}


def get_dynatrace_client():
    """FastAPI dependency, same shape as `get_db`: yields a client and
    closes its underlying HTTP connection when the request is done. Tests
    override this the same way they override `get_db`."""
    client = DynatraceClient()
    try:
        yield client
    finally:
        client.close()


class DynatraceClient:
    """Wrapper for the Dynatrace Metrics API v2 `GET /metrics/query` endpoint."""

    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self._settings = settings or get_settings()
        self._client = client or httpx.Client(
            base_url=self._settings.dynatrace_base_url,
            timeout=self._settings.dynatrace_timeout_seconds,
            headers={"Authorization": f"Api-Token {self._settings.dynatrace_api_token}"},
            verify=self._settings.dynatrace_verify_ssl,
        )

    def close(self) -> None:
        self._client.close()

    def list_rhel_hosts(self, page_size: int = 500) -> list[RhelHost]:
        """Discovers all RHEL host entities via the Dynatrace Entities API v2.

        Docs: https://docs.dynatrace.com/docs/dynatrace-api/environment-api/entity-v2/get-entities

        Scoped server-side to Linux (`entitySelector=type(HOST),osType(LINUX)`)
        then filtered client-side to `osVersion` containing "Red Hat", since
        Dynatrace does not expose a distro-level entitySelector filter --
        osType only distinguishes LINUX/WINDOWS/AIX/etc, not the distro.
        Paginates via `nextPageKey` until the full result set is fetched.
        """
        hosts: list[RhelHost] = []
        params: dict = {
            "entitySelector": "type(HOST),osType(LINUX)",
            "fields": "properties.osVersion",
            "pageSize": page_size,
        }
        next_page_key: str | None = None

        while True:
            request_params = {"nextPageKey": next_page_key} if next_page_key else params
            resp = self._client.get("/api/v2/entities", params=request_params)
            resp.raise_for_status()
            payload = resp.json()

            for entity in payload.get("entities", []):
                os_version = (entity.get("properties") or {}).get("osVersion") or ""
                if "red hat" not in os_version.lower():
                    continue
                hosts.append(
                    RhelHost(
                        entity_id=entity["entityId"],
                        hostname=entity.get("displayName", entity["entityId"]),
                        os_version=os_version or None,
                    )
                )

            next_page_key = payload.get("nextPageKey")
            if not next_page_key:
                break

        return hosts

    def list_disks_for_host(self, host_entity_id: str) -> list[DiskEntity]:
        """Lists the disk entities attached to a single host via the
        `isDiskOf` relationship, so DiskAdvisor knows every mount point that
        exists on the host -- not just the ones a metric query happens to
        return data for in the lookback window.
        """
        resp = self._client.get(
            "/api/v2/entities",
            params={
                "entitySelector": f"type(DISK),fromRelationships.isDiskOf({host_entity_id})",
                "fields": "properties.mountPoint",
            },
        )
        resp.raise_for_status()
        payload = resp.json()
        disks = []
        for entity in payload.get("entities", []):
            mount_point = (entity.get("properties") or {}).get("mountPoint") or entity.get("displayName", "/")
            disks.append(DiskEntity(entity_id=entity["entityId"], mount_point=mount_point, host_entity_id=host_entity_id))
        return disks

    def query_disk_usage(
        self,
        entity_ids: list[str] | None = None,
        usedpct_selector: str | None = None,
        available_selector: str | None = None,
        resolution: str = "1h",
        time_from: str = "-25h",
        batch_size: int | None = None,
    ) -> list[DiskUsagePoint]:
        """Queries usedPct + availableBytes for every disk/mount on every
        host in one call and returns merged data points (capacity_bytes and
        used_bytes populated whenever both metrics have a value for the same
        host/mount/timestamp). Callers (collector) turn these into DiskMetric
        rows.

        `entity_ids`, when given (the RHEL hosts from `list_rhel_hosts`),
        scopes the query server-side to just those hosts' disks via
        `entitySelector` -- metrics for non-RHEL hosts are never pulled.

        Dynatrace's Metrics API v2 query endpoint is GET-only, so there is no
        way to push a large `entityId(...)` list into a request body. With a
        6000-host fleet a single `entitySelector` easily exceeds URL length
        limits (414 Request-URI Too Large -- hit in practice around ~1800
        IDs). `entity_ids` is therefore split into chunks of `batch_size`
        (default `dynatrace_query_batch_size`, 100) and queried across
        multiple requests, concatenating the results.
        """
        usedpct_sel = usedpct_selector or self._settings.dynatrace_metric_usedpct_selector
        available_sel = available_selector or self._settings.dynatrace_metric_available_selector
        chunk_size = batch_size or self._settings.dynatrace_query_batch_size

        if not entity_ids:
            return self._query_disk_usage_page(usedpct_sel, available_sel, resolution, time_from, None)

        points: list[DiskUsagePoint] = []
        for i in range(0, len(entity_ids), chunk_size):
            chunk = entity_ids[i : i + chunk_size]
            points.extend(self._query_disk_usage_page(usedpct_sel, available_sel, resolution, time_from, chunk))
        return points

    def _query_disk_usage_page(
        self,
        usedpct_sel: str,
        available_sel: str,
        resolution: str,
        time_from: str,
        entity_ids: list[str] | None,
    ) -> list[DiskUsagePoint]:
        params = {
            "metricSelector": f"{usedpct_sel},{available_sel}",
            "resolution": resolution,
            "from": time_from,
        }
        if entity_ids:
            params["entitySelector"] = "type(HOST),entityId({})".format(",".join(entity_ids))
        resp = self._client.get("/api/v2/metrics/query", params=params)
        resp.raise_for_status()
        return self._parse_response(resp.json(), usedpct_sel, available_sel)

    def query_metrics(
        self,
        entity_id: str,
        metric_selectors: list[str],
        resolution: str = "1h",
        time_from: str = "-7d",
    ) -> dict[str, MetricSeries]:
        """Generic multi-metric time series query for a single host entity,
        used for on-demand correlation analysis (CPU/memory/network/disk I/O
        alongside a disk usage trend) -- not tied to any fixed set of metric
        names, so a tenant with different metric keys just needs a config
        change (`dynatrace_correlation_metrics`), not a code change.

        Returns a dict keyed by the *requested* metric selector (not
        Dynatrace's returned metricId, which may carry extra qualifiers) so
        callers can always look up what they asked for. A selector with no
        matching result in the response maps to an empty series rather than
        being omitted, so callers don't need to guard against missing keys.
        """
        if not metric_selectors:
            return {}

        resp = self._client.get(
            "/api/v2/metrics/query",
            params={
                "metricSelector": ",".join(metric_selectors),
                "entitySelector": f"type(HOST),entityId({entity_id})",
                "resolution": resolution,
                "from": time_from,
            },
        )
        resp.raise_for_status()
        payload = resp.json()

        series_by_selector: dict[str, MetricSeries] = {sel: MetricSeries(metric_id=sel, points=[]) for sel in metric_selectors}
        for result in payload.get("result", []):
            metric_id = result.get("metricId", "")
            matching_selector = next((sel for sel in metric_selectors if metric_id.startswith(sel)), None)
            if matching_selector is None:
                continue
            points: list[MetricPoint] = []
            for series in result.get("data", []):
                for ts, val in zip(series.get("timestamps", []), series.get("values", [])):
                    points.append(MetricPoint(timestamp_ms=ts, value=val))
            series_by_selector[matching_selector] = MetricSeries(metric_id=metric_id, points=points)

        return series_by_selector

    @staticmethod
    def _parse_response(payload: dict, usedpct_sel: str, available_sel: str) -> list[DiskUsagePoint]:
        # (entity_id, mount_point, timestamp_ms) -> value, one map per metric.
        usedpct_by_key: dict[tuple[str, str, int], float] = {}
        available_by_key: dict[tuple[str, str, int], float] = {}

        for result in payload.get("result", []):
            metric_id = result.get("metricId", "")
            target = usedpct_by_key if metric_id.startswith(usedpct_sel) else (
                available_by_key if metric_id.startswith(available_sel) else None
            )
            if target is None:
                continue
            for series in result.get("data", []):
                dims = series.get("dimensionMap", {}) or {}
                entity_id = dims.get("dt.entity.host") or dims.get("dt.entity.disk") or "unknown"
                mount_point = dims.get("mountPoint") or dims.get("disk") or "/"
                for ts, val in zip(series.get("timestamps", []), series.get("values", [])):
                    if val is None:
                        continue
                    target[(entity_id, mount_point, ts)] = val

        points: list[DiskUsagePoint] = []
        for key in sorted(set(usedpct_by_key) | set(available_by_key)):
            entity_id, mount_point, ts = key
            used_pct = usedpct_by_key.get(key)
            available_bytes = available_by_key.get(key)

            used_bytes: int | None = None
            capacity_bytes: int | None = None
            if used_pct is not None and available_bytes is not None and used_pct < 100.0:
                capacity_bytes = int(available_bytes / (1.0 - used_pct / 100.0))
                used_bytes = capacity_bytes - int(available_bytes)

            points.append(
                DiskUsagePoint(
                    entity_id=entity_id,
                    mount_point=mount_point,
                    timestamp_ms=ts,
                    used_pct=used_pct,
                    used_bytes=used_bytes,
                    capacity_bytes=capacity_bytes,
                )
            )
        return points
