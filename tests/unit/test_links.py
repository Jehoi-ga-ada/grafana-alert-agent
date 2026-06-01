"""Tests for pure Grafana link/URL builders."""

from __future__ import annotations

from gaa.clients.links import dashboard_url, dsolo_url, explore_logs_url, panel_url
from gaa.domain.models import TimeWindow

_W = TimeWindow(start=1700.0, end=2000.0)


def test_panel_url_includes_view_panel_and_range():
    url = panel_url("https://g.test", "abc", "dash", 8, _W)
    assert url.startswith("https://g.test/d/abc/dash?")
    assert "viewPanel=8" in url
    assert "from=1700000" in url and "to=2000000" in url


def test_dsolo_url_targets_solo_render():
    url = dsolo_url("https://g.test", "abc", "dash", 9, _W)
    assert "/d-solo/abc/dash?" in url
    assert "panelId=9" in url
    assert "theme=dark" in url


def test_dashboard_url_uses_bare_kiosk_flag():
    url = dashboard_url("https://g.test", "abc", "dash", _W)
    assert "/d/abc/dash?" in url
    assert url.endswith("&kiosk")  # bare flag, not kiosk=
    assert "from=1700000" in url


def test_explore_logs_url_embeds_query():
    url = explore_logs_url("https://g.test", "loki-uid", '{app="x"}', _W)
    assert url.startswith("https://g.test/explore?")
    assert "loki-uid" in url
