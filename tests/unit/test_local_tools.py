"""Tests for the local incident LangChain tools."""

from __future__ import annotations

import json

import pytest

from gaa.agent.local_tools import build_local_tools
from gaa.domain.models import Incident, Severity
from gaa.state.sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "s.db")
    yield s
    s.close()


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


class _FakeGrafana:
    async def list_dashboards(self):
        return [
            {"uid": "adrwn4x", "title": "URL Shortener — Group10 Logs", "slug": "logs", "tags": ["logs"]},
            {"uid": "ovw", "title": "URL Shortener — Group10 Overview", "slug": "ovw", "tags": ["observability"]},
        ]

    async def get_dashboard_panels(self, uid):
        return [{"id": 1, "title": "Errors", "type": "timeseries"}]


async def test_tools_exposed(store):
    tools = build_local_tools(store)
    assert {t.name for t in tools} == {"list_incidents", "get_incident"}


async def test_dashboard_tools_when_grafana_present(store):
    import json

    tools = build_local_tools(store, _FakeGrafana())
    names = {t.name for t in tools}
    assert {"list_dashboards", "list_dashboard_panels"} <= names

    out = json.loads(await _tool(tools, "list_dashboards").ainvoke({}))
    assert {d["uid"] for d in out} == {"adrwn4x", "ovw"}

    panels = json.loads(await _tool(tools, "list_dashboard_panels").ainvoke({"dashboard_uid": "ovw"}))
    assert panels[0]["title"] == "Errors"


async def test_list_and_get_incident(store):
    iid = await store.record_incident(
        Incident(rule_name="app_down", title="App down", severity=Severity.CRITICAL,
                 fired_at=1.0, summary="db dead", remediation=("restart pg",))
    )
    tools = build_local_tools(store)

    listing = json.loads(await _tool(tools, "list_incidents").ainvoke({"limit": 5}))
    assert listing[0]["id"] == iid
    assert listing[0]["open"] is True

    detail = json.loads(await _tool(tools, "get_incident").ainvoke({"incident_id": iid}))
    assert detail["title"] == "App down"
    assert detail["remediation"] == ["restart pg"]


async def test_get_missing_incident(store):
    tools = build_local_tools(store)
    out = await _tool(tools, "get_incident").ainvoke({"incident_id": 999})
    assert "not found" in out
