"""respx-mocked tests for the HTTP clients (no network)."""

from __future__ import annotations

import httpx
import pytest
import respx

from gaa.clients.discord import DiscordError, DiscordNotifier
from gaa.clients.grafana import GrafanaClient
from gaa.clients.loki import LogsClient
from gaa.clients.victoriametrics import MetricsClient
from gaa.domain.models import TimeWindow

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
async def test_metrics_query_instant_through_proxy(grafana):
    # Arrange
    respx.get(f"{_BASE}/api/datasources").mock(return_value=httpx.Response(200, json=_DS))
    respx.get(f"{_BASE}/api/datasources/proxy/uid/prom1/api/v1/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, "7"]}]},
            },
        )
    )
    metrics = MetricsClient(grafana)
    # Act
    result = await metrics.query_instant("up")
    # Assert
    assert result.samples[0].value == 7.0


@respx.mock
async def test_logs_query_returns_lines(grafana):
    respx.get(f"{_BASE}/api/datasources").mock(return_value=httpx.Response(200, json=_DS))
    respx.get(f"{_BASE}/api/datasources/proxy/uid/loki1/loki/api/v1/query_range").mock(
        return_value=httpx.Response(
            200,
            json={"status": "success", "data": {"result": [{"stream": {}, "values": [["5", "boom"]]}]}},
        )
    )
    logs = LogsClient(grafana)
    lines = await logs.query_logs('{app="x"}', TimeWindow(0, 10))
    assert lines == ("boom",)


@respx.mock
async def test_logs_query_swallows_errors(grafana):
    respx.get(f"{_BASE}/api/datasources").mock(return_value=httpx.Response(500))
    logs = LogsClient(grafana)
    assert await logs.query_logs("{}", TimeWindow(0, 10)) == ()


@respx.mock
async def test_discord_send_json_only():
    route = respx.post("https://discord.test/hook").mock(return_value=httpx.Response(204))
    notifier = DiscordNotifier("https://discord.test/hook")
    await notifier.send(embed={"title": "hi"})
    await notifier.aclose()
    assert route.called


@respx.mock
async def test_discord_send_with_image_uses_multipart():
    route = respx.post("https://discord.test/hook").mock(return_value=httpx.Response(200))
    notifier = DiscordNotifier("https://discord.test/hook")
    await notifier.send(embed={"title": "hi"}, image_png=b"\x89PNG", image_name="p.png")
    await notifier.aclose()
    request = route.calls.last.request
    assert b"multipart/form-data" in request.headers["content-type"].encode()


@respx.mock
async def test_discord_raises_on_error_status():
    respx.post("https://discord.test/hook").mock(return_value=httpx.Response(400, text="bad"))
    notifier = DiscordNotifier("https://discord.test/hook")
    with pytest.raises(DiscordError):
        await notifier.send(embed={})
    await notifier.aclose()
