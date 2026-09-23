"""Thin wrapper around Dynatrace Environment API v2.

 

Uses the Metrics API v2 for disk usage metrics and the Entities API v2 for

host/disk inventory.

 

Disk usage is collected from two builtin per-disk-instance metrics in a

single call (comma-joined metricSelector, one `result` entry per metric in

the response) and merged by (host entity, disk entity/mount, timestamp):

 

  - builtin:host.disk.usedPct

  - builtin:host.disk.availableBytes

 

usedPct alone has no absolute capacity, so capacity_bytes/used_bytes are

derived from the pair:

 

    capacity = available / (1 - usedPct/100)

 

Important Dynatrace entity-model detail for this tenant:

 

  - A DISK entity's `displayName` is the real mount point.

  - `properties.mountPoint` is NOT a valid DISK property.

  - The DISK -> HOST relationship is exposed as

    `fromRelationships.isDiskOf`, not `toRelationships.isDiskOf`.

 

Metric responses can contain `dt.entity.disk`. That entity ID is the

reliable key for resolving the real filesystem/mount through the Entities

API. The metric response's textual mount-point dimension must not be

treated as authoritative.

"""

 

from __future__ import annotations

 

from dataclasses import dataclass

 

import httpx

 

from app.core.config import Settings, get_settings

 

 

@dataclass

class DiskUsagePoint:

    entity_id: str

    mount_point: str | None

    timestamp_ms: int

    used_pct: float | None = None

    used_bytes: int | None = None

    capacity_bytes: int | None = None

 

    # dt.entity.disk from the metric response's dimensionMap, when present.

    # This is the reliable key for telling different filesystems on the same

    # host apart. Callers should resolve the real mount path from this ID via

    # list_all_disks()/Entities API rather than trusting textual mount-point

    # dimensions from the metric response.

    disk_entity_id: str | None = None

 

 

@dataclass

class RhelHost:

    """A RHEL host entity from the Dynatrace Entities API."""

 

    entity_id: str

    hostname: str

    os_version: str | None = None

 

 

@dataclass

class DiskEntity:

    """A disk entity attached to a host, from the Dynatrace Entities API."""

 

    entity_id: str

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

# listed here falls back to showing the raw selector as its own label.

CORRELATION_METRIC_LABELS: dict[str, tuple[str, str]] = {

    "builtin:host.cpu.usage": ("CPU kullanımı", "%"),

    "builtin:host.mem.usage": ("Bellek kullanımı", "%"),

    "builtin:host.disk.bytesRead": ("Disk okuma", "bytes/s"),

    "builtin:host.disk.bytesWritten": ("Disk yazma", "bytes/s"),

    "builtin:host.net.nic.bytesRx": ("Network alınan", "bytes/s"),

    "builtin:host.net.nic.bytesTx": ("Network gönderilen", "bytes/s"),

}

 

 

def get_dynatrace_client():

    """FastAPI dependency.

 

    Yields a DynatraceClient and closes its underlying HTTP connection when

    the request is complete. Tests can override this dependency in the same

    way they override get_db.

    """

    client = DynatraceClient()

    try:

        yield client

    finally:

        client.close()

 

 

class DynatraceClient:

    """Wrapper around Dynatrace Environment API v2 endpoints."""

 

    def __init__(

        self,

        settings: Settings | None = None,

        client: httpx.Client | None = None,

    ):

        self._settings = settings or get_settings()

        self._client = client or httpx.Client(

            base_url=self._settings.dynatrace_base_url,

            timeout=self._settings.dynatrace_timeout_seconds,

            headers={

                "Authorization": (

                    f"Api-Token {self._settings.dynatrace_api_token}"

                )

            },

            verify=self._settings.dynatrace_verify_ssl,

        )

 

    def close(self) -> None:

        self._client.close()

 

    def list_rhel_hosts(self, page_size: int = 500) -> list[RhelHost]:

        """Discover all RHEL host entities via Dynatrace Entities API v2.

 

        The query is scoped server-side to Linux:

 

            entitySelector=type(HOST),osType(LINUX)

 

        Distribution filtering is then performed client-side by checking

        whether osVersion contains "Red Hat".

 

        Pagination follows nextPageKey until the complete result set has

        been retrieved.

        """

        hosts: list[RhelHost] = []

 

        params: dict = {

            "entitySelector": "type(HOST),osType(LINUX)",

            "fields": "properties.osVersion",

            "pageSize": page_size,

        }

 

        next_page_key: str | None = None

 

        while True:

            request_params = (

                {"nextPageKey": next_page_key}

                if next_page_key

                else params

            )

 

            resp = self._client.get(

                "/api/v2/entities",

                params=request_params,

            )

            resp.raise_for_status()

 

            payload = resp.json()

 

            for entity in payload.get("entities", []):

                os_version = (

                    (entity.get("properties") or {}).get("osVersion") or ""

                )

 

                if "red hat" not in os_version.lower():

                    continue

 

                hosts.append(

                    RhelHost(

                        entity_id=entity["entityId"],

                        hostname=entity.get(

                            "displayName",

                            entity["entityId"],

                        ),

                        os_version=os_version or None,

                    )

                )

 

            next_page_key = payload.get("nextPageKey")

 

            if not next_page_key:

                break

 

        return hosts

 

    def list_disks_for_host(

        self,

        host_entity_id: str,

        page_size: int = 500,

    ) -> list[DiskEntity]:

        """List all DISK entities attached to one host.

 

        Dynatrace's DISK entity model in this tenant exposes:

 

          - displayName:

              the actual filesystem mount point

 

          - fromRelationships.isDiskOf:

              the HOST relationship

 

        `properties.mountPoint` must NOT be requested because it is not a

        valid property for the DISK entity type in this tenant.

 

        This method is intended for ad-hoc/manual lookups. Fleet-wide

        collection should use list_all_disks() to avoid one request per host.

        """

        disks: list[DiskEntity] = []

 

        params: dict = {

            "entitySelector": (

                "type(DISK),"

                f"fromRelationships.isDiskOf({host_entity_id})"

            ),

            "fields": "properties.filesystemType",

            "pageSize": page_size,

        }

 

        next_page_key: str | None = None

 

        while True:

            request_params = (

                {"nextPageKey": next_page_key}

                if next_page_key

                else params

            )

 

            resp = self._client.get(

                "/api/v2/entities",

                params=request_params,

            )

            resp.raise_for_status()

 

            payload = resp.json()

 

            for entity in payload.get("entities", []):

                entity_id = entity.get("entityId")

 

                if not entity_id:

                    continue

 

                mount_point = entity.get("displayName")

 

                if not mount_point:

                    continue

 

                disks.append(

                    DiskEntity(

                        entity_id=entity_id,

                        mount_point=mount_point,

                        host_entity_id=host_entity_id,

                    )

                )

 

            next_page_key = payload.get("nextPageKey")

 

            if not next_page_key:

                break

 

        return disks

 

    def list_all_disks(

        self,

        page_size: int = 500,

    ) -> list[DiskEntity]:

        """Perform a fleet-wide DISK entity inventory scan.

 

        This method provides the authoritative mapping:

 

            DISK entity ID

                -> HOST entity ID

                -> real mount point

 

        The live tenant's DISK schema exposes:

 

            displayName

                Real mount point, for example:

                /, /tmp, /u01, /opt/agents

 

            properties.filesystemType

                Filesystem type such as xfs.

 

            fromRelationships.isDiskOf

                Relationship from the DISK entity to its HOST.

 

        There is no `properties.mountPoint` field for DISK entities in this

        tenant, and `isDiskOf` is a fromRelationship rather than a

        toRelationship.

 

        The method performs one paginated fleet-wide entity scan instead of

        one request per host.

 

        DISK entities without a resolvable HOST relationship or without a

        usable displayName are skipped because they cannot safely be mapped

        into DiskAdvisor's host/filesystem model.

        """

        disks: list[DiskEntity] = []

 

        params: dict = {

            "entitySelector": "type(DISK)",

            "fields": (

                "properties.filesystemType,"

                "fromRelationships.isDiskOf"

            ),

            "pageSize": page_size,

        }

 

        next_page_key: str | None = None

 

        while True:

            request_params = (

                {"nextPageKey": next_page_key}

                if next_page_key

                else params

            )

 

            resp = self._client.get(

                "/api/v2/entities",

                params=request_params,

            )

            resp.raise_for_status()

 

            payload = resp.json()

 

            for entity in payload.get("entities", []):

                entity_id = entity.get("entityId")

 

                if not entity_id:

                    continue

 

                # On this Dynatrace tenant the DISK displayName is the

                # authoritative filesystem mount point.

                mount_point = entity.get("displayName")

 

                if not mount_point:

                    continue

 

                host_refs = (

                    (entity.get("fromRelationships") or {})

                    .get("isDiskOf")

                    or []

                )

 

                if not host_refs:

                    continue

 

                # A DISK normally belongs to exactly one HOST. Be defensive

                # about both the normal object representation:

                #

                #   {"id": "HOST-...", "type": "HOST"}

                #

                # and a possible raw ID representation.

                first_host_ref = host_refs[0]

 

                if isinstance(first_host_ref, dict):

                    host_entity_id = first_host_ref.get("id")

                else:

                    host_entity_id = first_host_ref

 

                if not host_entity_id:

                    continue

 

                disks.append(

                    DiskEntity(

                        entity_id=entity_id,

                        mount_point=mount_point,

                        host_entity_id=host_entity_id,

                    )

                )

 

            next_page_key = payload.get("nextPageKey")

 

            if not next_page_key:

                break

 

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

        """Query usedPct + availableBytes for disk instances.

 

        The returned metric points are merged by host/disk/timestamp.

 

        When both usedPct and availableBytes exist for the same point,

        capacity_bytes and used_bytes are derived.

 

        `entity_ids`, when supplied, contains the RHEL HOST entity IDs and

        scopes the metric query server-side to those hosts.

 

        Dynatrace Metrics API v2 uses GET. A large fleet therefore cannot

        safely put thousands of HOST entity IDs into one URL. entity_ids is

        split into batches according to dynatrace_query_batch_size.

        """

        usedpct_sel = (

            usedpct_selector

            or self._settings.dynatrace_metric_usedpct_selector

        )

 

        available_sel = (

            available_selector

            or self._settings.dynatrace_metric_available_selector

        )

 

        chunk_size = (

            batch_size

            or self._settings.dynatrace_query_batch_size

        )

 

        if not entity_ids:

            return self._query_disk_usage_page(

                usedpct_sel,

                available_sel,

                resolution,

                time_from,

                None,

            )

 

        points: list[DiskUsagePoint] = []

 

        for i in range(0, len(entity_ids), chunk_size):

            chunk = entity_ids[i:i + chunk_size]

 

            points.extend(

                self._query_disk_usage_page(

                    usedpct_sel,

                    available_sel,

                    resolution,

                    time_from,

                    chunk,

                )

            )

 

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

            params["entitySelector"] = (

                "type(HOST),entityId({})".format(

                    ",".join(entity_ids)

                )

            )

 

        resp = self._client.get(

            "/api/v2/metrics/query",

            params=params,

        )

        resp.raise_for_status()

 

        return self._parse_response(

            resp.json(),

            usedpct_sel,

            available_sel,

        )

 

    def query_metrics(

        self,

        entity_id: str,

        metric_selectors: list[str],

        resolution: str = "1h",

        time_from: str = "-7d",

    ) -> dict[str, MetricSeries]:

        """Query arbitrary correlation metrics for a single HOST entity.

 

        The result dictionary is keyed by the metric selector requested by

        the caller. A selector for which Dynatrace returns no data is still

        included with an empty MetricSeries.

        """

        if not metric_selectors:

            return {}

 

        resp = self._client.get(

            "/api/v2/metrics/query",

            params={

                "metricSelector": ",".join(metric_selectors),

                "entitySelector": (

                    f"type(HOST),entityId({entity_id})"

                ),

                "resolution": resolution,

                "from": time_from,

            },

        )

 

        resp.raise_for_status()

        payload = resp.json()

 

        series_by_selector: dict[str, MetricSeries] = {

            selector: MetricSeries(

                metric_id=selector,

                points=[],

            )

            for selector in metric_selectors

        }

 

        for result in payload.get("result", []):

            metric_id = result.get("metricId", "")

 

            matching_selector = next(

                (

                    selector

                    for selector in metric_selectors

                    if metric_id.startswith(selector)

                ),

                None,

            )

 

            if matching_selector is None:

                continue

 

            points: list[MetricPoint] = []

 

            for series in result.get("data", []):

                timestamps = series.get("timestamps", [])

                values = series.get("values", [])

 

                for timestamp, value in zip(timestamps, values):

                    points.append(

                        MetricPoint(

                            timestamp_ms=timestamp,

                            value=value,

                        )

                    )

 

            series_by_selector[matching_selector] = MetricSeries(

                metric_id=metric_id,

                points=points,

            )

 

        return series_by_selector

 

    @staticmethod

    def _parse_response(

        payload: dict,

        usedpct_sel: str,

        available_sel: str,

    ) -> list[DiskUsagePoint]:

        """Parse and merge Dynatrace disk metric series.

 

        Merge key:

 

            (HOST entity ID, disk key, timestamp)

 

        `dt.entity.disk` is preferred as disk_key because it uniquely

        identifies a filesystem/disk entity and can be resolved against the

        Entities API inventory.

 

        Textual mount-point dimensions are used only as a fallback when

        dt.entity.disk is unavailable.

 

        A hard-coded "/" fallback is deliberately NOT used because doing so

        can merge multiple filesystems on the same host into one logical

        disk and produce invalid usage figures.

        """

        usedpct_by_key: dict[

            tuple[str, str, int],

            float,

        ] = {}

 

        available_by_key: dict[

            tuple[str, str, int],

            float,

        ] = {}

 

        mount_text_by_disk_key: dict[str, str] = {}

        disk_entity_id_by_key: dict[str, str] = {}

 

        for result in payload.get("result", []):

            metric_id = result.get("metricId", "")

 

            if metric_id.startswith(usedpct_sel):

                target = usedpct_by_key

            elif metric_id.startswith(available_sel):

                target = available_by_key

            else:

                target = None

 

            if target is None:

                continue

 

            for series in result.get("data", []):

                dims = series.get("dimensionMap", {}) or {}

 

                entity_id = (

                    dims.get("dt.entity.host")

                    or "unknown"

                )

 

                disk_entity_id = dims.get("dt.entity.disk")

 

                mount_text = (

                    dims.get("mountPoint")

                    or dims.get("disk")

                )

 

                disk_key = (

                    disk_entity_id

                    or mount_text

                    or "unknown"

                )

 

                if mount_text:

                    mount_text_by_disk_key[disk_key] = mount_text

 

                if disk_entity_id:

                    disk_entity_id_by_key[disk_key] = disk_entity_id

 

                timestamps = series.get("timestamps", [])

                values = series.get("values", [])

 

                for timestamp, value in zip(timestamps, values):

                    if value is None:

                        continue

 

                    target[

                        (

                            entity_id,

                            disk_key,

                            timestamp,

                        )

                    ] = value

 

        points: list[DiskUsagePoint] = []

 

        all_keys = (

            set(usedpct_by_key)

            | set(available_by_key)

        )

 

        for key in sorted(all_keys):

            entity_id, disk_key, timestamp = key

 

            used_pct = usedpct_by_key.get(key)

            available_bytes = available_by_key.get(key)

 

            used_bytes: int | None = None

            capacity_bytes: int | None = None

 

            if (

                used_pct is not None

                and available_bytes is not None

                and used_pct < 100.0

            ):

                capacity_bytes = int(

                    available_bytes

                    / (1.0 - used_pct / 100.0)

                )

 

                used_bytes = (

                    capacity_bytes

                    - int(available_bytes)

                )

 

            points.append(

                DiskUsagePoint(

                    entity_id=entity_id,

                    mount_point=(

                        mount_text_by_disk_key.get(disk_key)

                    ),

                    timestamp_ms=timestamp,

                    used_pct=used_pct,

                    used_bytes=used_bytes,

                    capacity_bytes=capacity_bytes,

                    disk_entity_id=(

                        disk_entity_id_by_key.get(disk_key)

                    ),

                )

            )

 

        return points