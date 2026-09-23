import httpx

from app.core.config import Settings
from app.services.dynatrace_client import DynatraceClient


SAMPLE_RESPONSE = {
    "result": [
        {
            "metricId": "builtin:host.disk.usedPct",
            "data": [
                {
                    "dimensionMap": {"dt.entity.host": "HOST-123", "mountPoint": "/var"},
                    "timestamps": [1700000000000, 1700003600000],
                    "values": [80.0, 90.0],
                }
            ],
        },
        {
            "metricId": "builtin:host.disk.availableBytes",
            "data": [
                {
                    "dimensionMap": {"dt.entity.host": "HOST-123", "mountPoint": "/var"},
                    "timestamps": [1700000000000, 1700003600000],
                    "values": [20 * 1024 ** 3, 10 * 1024 ** 3],
                }
            ],
        },
    ]
}


def test_query_disk_usage_parses_and_merges_both_metrics():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "usedPct" in request.url.params["metricSelector"]
        assert "availableBytes" in request.url.params["metricSelector"]
        return httpx.Response(200, json=SAMPLE_RESPONSE)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://fake.dynatrace.example")
    client = DynatraceClient(client=http_client)

    # Selectors passed explicitly so this test doesn't depend on the config
    # default (which is tenant-specific -- see config.py's comment on why
    # the real default is `builtin:host.disk.avail`, not `availableBytes`).
    points = client.query_disk_usage(
        usedpct_selector="builtin:host.disk.usedPct",
        available_selector="builtin:host.disk.availableBytes",
    )

    assert len(points) == 2
    first = points[0]
    assert first.entity_id == "HOST-123"
    assert first.mount_point == "/var"
    assert first.used_pct == 80.0
    # available=20GB at 80% used -> capacity=100GB, used=80GB
    assert first.capacity_bytes == 100 * 1024 ** 3
    assert first.used_bytes == 80 * 1024 ** 3


def test_dynatrace_verify_ssl_setting_propagates_to_client(monkeypatch):
    captured = {}
    real_client_cls = httpx.Client

    def client_factory(*args, **kwargs):
        captured["verify"] = kwargs.get("verify")
        kwargs["transport"] = httpx.MockTransport(lambda r: httpx.Response(200, json={"result": []}))
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_factory)

    DynatraceClient(settings=Settings(dynatrace_verify_ssl=False))

    assert captured["verify"] is False


def test_query_disk_usage_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://fake.dynatrace.example")
    client = DynatraceClient(client=http_client)

    try:
        client.query_disk_usage()
        assert False, "should have raised"
    except httpx.HTTPStatusError:
        pass


def test_query_disk_usage_scopes_to_given_entity_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["entitySelector"] == "type(HOST),entityId(HOST-1,HOST-2)"
        return httpx.Response(200, json={"result": []})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://fake.dynatrace.example")
    client = DynatraceClient(client=http_client)

    client.query_disk_usage(entity_ids=["HOST-1", "HOST-2"])


def test_query_disk_usage_batches_large_entity_id_lists():
    """A large fleet must not be queried in one URL -- Dynatrace's Metrics
    API v2 query endpoint is GET-only and a single entitySelector scoped to
    ~1800+ hosts hits 414 Request-URI Too Large in practice."""
    seen_selectors = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_selectors.append(request.url.params["entitySelector"])
        return httpx.Response(200, json={"result": []})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://fake.dynatrace.example")
    client = DynatraceClient(client=http_client, settings=Settings(dynatrace_query_batch_size=2))

    entity_ids = ["HOST-1", "HOST-2", "HOST-3", "HOST-4", "HOST-5"]
    client.query_disk_usage(entity_ids=entity_ids)

    assert len(seen_selectors) == 3  # ceil(5/2)
    assert seen_selectors[0] == "type(HOST),entityId(HOST-1,HOST-2)"
    assert seen_selectors[1] == "type(HOST),entityId(HOST-3,HOST-4)"
    assert seen_selectors[2] == "type(HOST),entityId(HOST-5)"


ENTITIES_RHEL_PAGE_1 = {
    "entities": [
        {"entityId": "HOST-RHEL1", "displayName": "app01", "properties": {"osVersion": "Red Hat Enterprise Linux 8.6"}},
        {"entityId": "HOST-WIN1", "displayName": "win01", "properties": {"osVersion": "Windows Server 2019"}},
    ],
    "nextPageKey": "page2token",
}
ENTITIES_RHEL_PAGE_2 = {
    "entities": [
        {"entityId": "HOST-RHEL2", "displayName": "app02", "properties": {"osVersion": "Red Hat Enterprise Linux 9.2"}},
    ],
}


def test_list_rhel_hosts_filters_os_version_and_paginates():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if "nextPageKey" in request.url.params:
            return httpx.Response(200, json=ENTITIES_RHEL_PAGE_2)
        assert request.url.params["entitySelector"] == "type(HOST),osType(LINUX)"
        return httpx.Response(200, json=ENTITIES_RHEL_PAGE_1)

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://fake.dynatrace.example")
    client = DynatraceClient(client=http_client)

    hosts = client.list_rhel_hosts()

    assert len(calls) == 2
    assert [h.entity_id for h in hosts] == ["HOST-RHEL1", "HOST-RHEL2"]
    assert hosts[0].hostname == "app01"
    assert hosts[0].os_version == "Red Hat Enterprise Linux 8.6"


def test_query_metrics_maps_by_requested_selector_and_fills_gaps():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["entitySelector"] == "type(HOST),entityId(HOST-1)"
        assert "builtin:host.cpu.usage" in request.url.params["metricSelector"]
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "metricId": "builtin:host.cpu.usage:avg",
                        "data": [{"timestamps": [1700000000000], "values": [55.5]}],
                    }
                    # builtin:host.mem.usage requested but absent from response entirely.
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://fake.dynatrace.example")
    client = DynatraceClient(client=http_client)

    series = client.query_metrics("HOST-1", ["builtin:host.cpu.usage", "builtin:host.mem.usage"])

    assert series["builtin:host.cpu.usage"].points[0].value == 55.5
    assert series["builtin:host.mem.usage"].points == []  # present but empty, not missing


def test_list_disks_for_host():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "fromRelationships.isDiskOf(HOST-RHEL1)" in request.url.params["entitySelector"]
        return httpx.Response(
            200,
            json={
                "entities": [
                    {"entityId": "DISK-1", "displayName": "/var", "properties": {"mountPoint": "/var"}},
                    {"entityId": "DISK-2", "displayName": "/", "properties": {"mountPoint": "/"}},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="https://fake.dynatrace.example")
    client = DynatraceClient(client=http_client)

    disks = client.list_disks_for_host("HOST-RHEL1")

    assert len(disks) == 2
    assert disks[0].mount_point == "/var"
    assert disks[0].host_entity_id == "HOST-RHEL1"
