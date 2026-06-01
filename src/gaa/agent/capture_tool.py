"""A LangChain tool that screenshots a Grafana panel the agent chooses.

The agent discovers dashboards/panels dynamically (search_dashboards,
get_dashboard_by_uid) and calls this to capture any panel. The PNG is stashed in
the current ScreenshotCollector for the bot to attach.
"""

from __future__ import annotations

import time

from langchain_core.tools import StructuredTool

from gaa.agent.screenshots import get_collector
from gaa.clients.protocols import Capturer
from gaa.domain.models import TimeWindow

_DESCRIPTION = (
    "Screenshot a specific Grafana panel and attach it to the reply. "
    "Args: dashboard_uid (from search_dashboards/get_dashboard_by_uid), panel_id (int), "
    "minutes (lookback, default 60). Find the uid and panel id first with the dashboard tools."
)


def build_capture_tool(capturer: Capturer, clock=time.time) -> StructuredTool:
    async def capture_panel(dashboard_uid: str, panel_id: int, minutes: int = 60) -> str:
        now = clock()
        window = TimeWindow(now - max(1, minutes) * 60, now)
        png = await capturer.capture_panel(panel_id, window, dashboard_uid=dashboard_uid)
        if png is None:
            return (
                f"Screenshot failed for panel {panel_id} on dashboard {dashboard_uid} — the "
                "dashboard may not be readable by the service account, or the panel id is wrong."
            )
        collector = get_collector()
        if collector is not None:
            collector.add(f"{dashboard_uid}-panel{panel_id}.png", png)
            return f"Captured panel {panel_id} from dashboard {dashboard_uid}; image attached to the reply."
        return f"Captured panel {panel_id} from dashboard {dashboard_uid}."

    return StructuredTool.from_function(
        coroutine=capture_panel, name="capture_panel", description=_DESCRIPTION
    )


_DASH_DESCRIPTION = (
    "Screenshot a WHOLE Grafana dashboard (all panels) and attach it to the reply. "
    "Args: dashboard_uid (from list_dashboards), minutes (lookback, default 60). "
    "Use capture_panel instead if you only need one panel."
)


def build_capture_dashboard_tool(capturer: Capturer, clock=time.time) -> StructuredTool:
    async def capture_dashboard(dashboard_uid: str, minutes: int = 60) -> str:
        now = clock()
        window = TimeWindow(now - max(1, minutes) * 60, now)
        png = await capturer.capture_dashboard(window, dashboard_uid=dashboard_uid)
        if png is None:
            return (
                f"Screenshot failed for dashboard {dashboard_uid} — it may not be readable by the "
                "service account, or the uid is wrong (use list_dashboards)."
            )
        collector = get_collector()
        if collector is not None:
            collector.add(f"{dashboard_uid}-dashboard.png", png)
            return f"Captured the full {dashboard_uid} dashboard; image attached to the reply."
        return f"Captured the full {dashboard_uid} dashboard."

    return StructuredTool.from_function(
        coroutine=capture_dashboard, name="capture_dashboard", description=_DASH_DESCRIPTION
    )
