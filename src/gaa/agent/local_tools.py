"""Local read-only LangChain tools (incident history from SQLite).

These are NOT redundant with mcp-grafana — the incident store is the agent's own
memory of past alerts. Metric/log queries are handled by the MCP Grafana tools.
"""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool

from gaa.state.store import StateStore


def build_local_tools(store: StateStore, grafana=None) -> list:
    async def list_incidents(limit: int = 10) -> str:
        """List recent alert incidents recorded by the agent (id, title, severity, state)."""
        incidents = await store.list_incidents(max(1, min(limit, 50)))
        return json.dumps(
            [
                {
                    "id": i.id,
                    "rule": i.rule_name,
                    "title": i.title,
                    "severity": i.severity.value,
                    "open": i.is_open,
                    "fired_at": i.fired_at,
                    "summary": i.summary,
                }
                for i in incidents
            ]
        )

    async def get_incident(incident_id: int) -> str:
        """Get full details of one incident by id (AI summary, cause, remediation)."""
        incident = await store.get_incident(incident_id)
        if incident is None:
            return f"incident {incident_id} not found"
        return json.dumps(
            {
                "id": incident.id,
                "rule": incident.rule_name,
                "title": incident.title,
                "severity": incident.severity.value,
                "open": incident.is_open,
                "summary": incident.summary,
                "likely_cause": incident.likely_cause,
                "remediation": list(incident.remediation),
                "dashboard_url": incident.dashboard_url,
            }
        )

    tools = [
        StructuredTool.from_function(
            coroutine=list_incidents,
            name="list_incidents",
            description="List recent alert incidents recorded by this agent.",
        ),
        StructuredTool.from_function(
            coroutine=get_incident,
            name="get_incident",
            description="Get full details (analysis + remediation) of one incident by its id.",
        ),
    ]

    if grafana is not None:
        async def list_dashboards() -> str:
            """List ALL Grafana dashboards (uid, title, tags). Use this to discover dashboards."""
            dashboards = await grafana.list_dashboards()
            return json.dumps(
                [{"uid": d["uid"], "title": d["title"], "tags": d.get("tags", [])} for d in dashboards]
            )

        async def list_dashboard_panels(dashboard_uid: str) -> str:
            """List a dashboard's panels as {id, title, type}. Use BEFORE capture_panel
            to pick the right panel id for the metric you want."""
            panels = await grafana.get_dashboard_panels(dashboard_uid)
            return json.dumps(panels)

        tools.append(
            StructuredTool.from_function(
                coroutine=list_dashboards,
                name="list_dashboards",
                description="List ALL Grafana dashboards with their uid, title and tags. "
                "Authoritative — use this (not search) to find a dashboard's uid.",
            )
        )
        tools.append(
            StructuredTool.from_function(
                coroutine=list_dashboard_panels,
                name="list_dashboard_panels",
                description="List a dashboard's panels (id, title, type) for a given dashboard uid. "
                "Call this before capture_panel so you screenshot the RIGHT panel by its title.",
            )
        )
    return tools
