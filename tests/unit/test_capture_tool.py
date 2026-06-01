"""Tests for the dynamic screenshot collector + capture_panel tool."""

from __future__ import annotations

from gaa.agent.capture_tool import build_capture_dashboard_tool, build_capture_tool
from gaa.agent.screenshots import ScreenshotCollector, reset_collector, set_collector
from tests.fakes import FakeCapturer


async def test_capture_dashboard_tool_collects():
    tool = build_capture_dashboard_tool(FakeCapturer(b"PNG"), clock=lambda: 1000.0)
    collector = ScreenshotCollector()
    token = set_collector(collector)
    try:
        out = await tool.ainvoke({"dashboard_uid": "dash1", "minutes": 30})
    finally:
        reset_collector(token)
    assert "full dash1 dashboard" in out
    assert collector.drain() == [("dash1-dashboard.png", b"PNG")]


class TestScreenshotCollector:
    def test_add_and_drain(self):
        c = ScreenshotCollector()
        c.add("a.png", b"1")
        c.add("b.png", b"2")
        assert c.drain() == [("a.png", b"1"), ("b.png", b"2")]
        assert c.drain() == []  # drained


class TestCaptureTool:
    async def test_captures_into_active_collector(self):
        tool = build_capture_tool(FakeCapturer(b"PNG"), clock=lambda: 1000.0)
        collector = ScreenshotCollector()
        token = set_collector(collector)
        try:
            out = await tool.ainvoke({"dashboard_uid": "dash1", "panel_id": 8, "minutes": 30})
        finally:
            reset_collector(token)
        assert "Captured panel 8" in out
        assert collector.drain() == [("dash1-panel8.png", b"PNG")]

    async def test_failed_capture_reports_permission_hint(self):
        tool = build_capture_tool(FakeCapturer(None), clock=lambda: 1000.0)
        collector = ScreenshotCollector()
        token = set_collector(collector)
        try:
            out = await tool.ainvoke({"dashboard_uid": "dash1", "panel_id": 8})
        finally:
            reset_collector(token)
        assert "failed" in out.lower()
        assert collector.drain() == []

    async def test_no_collector_still_succeeds(self):
        tool = build_capture_tool(FakeCapturer(b"PNG"), clock=lambda: 1.0)
        out = await tool.ainvoke({"dashboard_uid": "d", "panel_id": 1})
        assert "Captured panel 1" in out
