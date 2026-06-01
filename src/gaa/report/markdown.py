"""Pure markdown rendering for an incident report (archival attachment)."""

from __future__ import annotations

from datetime import datetime, timezone

from gaa.domain.models import Incident


def _ts(epoch: float | None) -> str:
    if epoch is None:
        return "—"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def render_report_markdown(incident: Incident, body: str, tools: list[str]) -> str:
    """Render a full incident report as markdown."""
    lines = [
        f"# Incident Report — {incident.title}",
        "",
        f"- **ID:** {incident.id}",
        f"- **Rule:** {incident.rule_name}",
        f"- **Severity:** {incident.severity.value}",
        f"- **Status:** {'open' if incident.is_open else 'resolved'}",
        f"- **Fired:** {_ts(incident.fired_at)}",
        f"- **Resolved:** {_ts(incident.resolved_at)}",
        f"- **Observed value:** {incident.value if incident.value is not None else '—'}",
        "",
        "## Investigation",
        "",
        body.strip() or "_No analysis produced._",
        "",
        "## Stored summary",
        "",
        incident.summary or "_none_",
    ]
    if incident.likely_cause:
        lines += ["", "## Recorded likely cause", "", incident.likely_cause]
    if incident.remediation:
        lines += ["", "## Recorded remediation"] + [f"{i}. {s}" for i, s in enumerate(incident.remediation, 1)]
    if incident.dashboard_url:
        lines += ["", f"[Open in Grafana]({incident.dashboard_url})"]
    lines += ["", f"_Tools used: {', '.join(tools) or 'none'}_"]
    return "\n".join(lines)
