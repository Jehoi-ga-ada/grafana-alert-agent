"""respx tests for the Grafana transport (datasource discovery, health, search)."""

from __future__ import annotations

import httpx
import pytest
import respx

from gaa.clients.grafana import GrafanaClient, GrafanaError

_BASE = "https://grafana.test"
_DS = [
    {"uid": "prom1", "type": "prometheus", "name": "VM"},
    {"uid": "loki1", "type": "loki", "name": "loki"},
]


@pytest.fixture
async def grafana():
    client = GrafanaClient(_BASE, token="tok", verify=False)
    yield client
    await client.aclose()


@respx.mock
async def test_health(grafana):
    respx.get(f"{_BASE}/api/health").mock(
        return_value=httpx.Response(200, json={"database": "ok", "version": "13.0.1"})
    )
    health = await grafana.health()
    assert health["version"] == "13.0.1"


@respx.mock
async def test_resolve_datasource_uid_caches(grafana):
    route = respx.get(f"{_BASE}/api/datasources").mock(return_value=httpx.Response(200, json=_DS))
    assert await grafana.resolve_datasource_uid("loki") == "loki1"
    assert await grafana.resolve_datasource_uid("loki") == "loki1"  # cached
    assert route.call_count == 1


@respx.mock
async def test_resolve_unknown_datasource_raises(grafana):
    respx.get(f"{_BASE}/api/datasources").mock(return_value=httpx.Response(200, json=_DS))
    with pytest.raises(GrafanaError, match="no datasource"):
        await grafana.resolve_datasource_uid("influxdb")


@respx.mock
async def test_proxy_get_wraps_http_errors(grafana):
    respx.get(f"{_BASE}/api/datasources/proxy/uid/x/api/v1/query").mock(
        return_value=httpx.Response(502)
    )
    with pytest.raises(GrafanaError):
        await grafana.proxy_get("x", "api/v1/query", {"query": "up"})


@respx.mock
async def test_search_dashboard_uid(grafana):
    respx.get(f"{_BASE}/api/search").mock(
        return_value=httpx.Response(200, json=[{"uid": "dash9", "title": "url-shortener"}])
    )
    assert await grafana.search_dashboard_uid("url-shortener") == "dash9"


@respx.mock
async def test_search_dashboard_uid_none_when_empty(grafana):
    respx.get(f"{_BASE}/api/search").mock(return_value=httpx.Response(200, json=[]))
    assert await grafana.search_dashboard_uid("missing") is None


@respx.mock
async def test_list_dashboards(grafana):
    respx.get(f"{_BASE}/api/search").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"uid": "abc", "title": "Logs", "uri": "db/url-shortener-logs"},
                {"uid": "def", "title": "Traces", "uri": "db/url-shortener-traces"},
            ],
        )
    )
    dashboards = await grafana.list_dashboards()
    assert {d["uid"] for d in dashboards} == {"abc", "def"}
    assert dashboards[0]["slug"] == "url-shortener-logs"


@respx.mock
async def test_get_dashboard_panels_flattens_rows(grafana):
    respx.get(f"{_BASE}/api/dashboards/uid/abc").mock(
        return_value=httpx.Response(
            200,
            json={
                "dashboard": {
                    "panels": [
                        {"id": 1, "title": "Errors", "type": "timeseries"},
                        {"id": 100, "title": "Row", "type": "row", "panels": [
                            {"id": 2, "title": "Latency", "type": "timeseries"},
                        ]},
                    ]
                }
            },
        )
    )
    panels = await grafana.get_dashboard_panels("abc")
    assert [p["id"] for p in panels] == [1, 2]  # row flattened, row itself skipped
    assert panels[1]["title"] == "Latency"
