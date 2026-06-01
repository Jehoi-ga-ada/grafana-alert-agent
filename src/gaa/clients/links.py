"""Pure builders for Grafana deep links and render URLs (no I/O)."""

from __future__ import annotations

from urllib.parse import urlencode

from gaa.domain.models import TimeWindow


def panel_url(base: str, uid: str, slug: str, panel_id: int, window: TimeWindow) -> str:
    """Link to a single panel on its dashboard at the firing time range."""
    query = urlencode(
        {"viewPanel": panel_id, "from": window.start_ms, "to": window.end_ms}
    )
    return f"{base}/d/{uid}/{slug}?{query}"


def dsolo_url(
    base: str,
    uid: str,
    slug: str,
    panel_id: int,
    window: TimeWindow,
    theme: str = "dark",
) -> str:
    """Solo-panel render URL — what Playwright navigates to for a clean screenshot."""
    query = urlencode(
        {
            "panelId": panel_id,
            "from": window.start_ms,
            "to": window.end_ms,
            "theme": theme,
            "kiosk": "",
        }
    )
    return f"{base}/d-solo/{uid}/{slug}?{query}"


def dashboard_url(
    base: str, uid: str, slug: str, window: TimeWindow, theme: str = "dark"
) -> str:
    """Full-dashboard kiosk URL — for whole-dashboard screenshots.

    `kiosk` is appended as a bare flag (Grafana treats `?kiosk` as the boolean that
    hides the nav + top bar; `kiosk=` is NOT honored by newer versions).
    """
    query = urlencode({"from": window.start_ms, "to": window.end_ms, "theme": theme})
    return f"{base}/d/{uid}/{slug}?{query}&kiosk"


def explore_logs_url(base: str, loki_uid: str, logql: str, window: TimeWindow) -> str:
    """Link to Grafana Explore pre-filled with a LogQL query."""
    import json

    state = {
        "datasource": loki_uid,
        "queries": [{"refId": "A", "expr": logql}],
        "range": {"from": str(window.start_ms), "to": str(window.end_ms)},
    }
    query = urlencode({"schemaVersion": 1, "panes": json.dumps({"log": state}), "orgId": 1})
    return f"{base}/explore?{query}"
