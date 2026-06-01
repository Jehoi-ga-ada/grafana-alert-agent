"""Pure prompt assembly. Stable playbook → cacheable system block; only the
incident specifics vary per call (good for cost + snapshot testing)."""

from __future__ import annotations

from datetime import datetime, timezone

from gaa.analyzer.playbook import system_prefix
from gaa.enrichment.context import ContextBundle

# Tool that forces Claude to return structured analysis.
ANALYSIS_TOOL = {
    "name": "report_analysis",
    "description": "Report your root-cause analysis of the fired alert.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One or two sentences: what is happening and how bad.",
            },
            "likely_cause": {
                "type": "string",
                "description": "The single most likely root cause, with reasoning from the data.",
            },
            "remediation_steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered, specific steps/commands an operator can run. Most useful first.",
            },
            "severity": {
                "type": "string",
                "enum": ["critical", "high", "warning", "info"],
            },
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
        "required": ["summary", "likely_cause", "remediation_steps", "severity", "confidence"],
    },
}


def system_blocks() -> list[dict]:
    """System content with prompt caching on the stable playbook prefix."""
    return [
        {
            "type": "text",
            "text": system_prefix(),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _fmt_window(bundle: ContextBundle) -> str:
    start = datetime.fromtimestamp(bundle.window.start, tz=timezone.utc).strftime("%H:%M:%S")
    end = datetime.fromtimestamp(bundle.window.end, tz=timezone.utc).strftime("%H:%M:%S UTC")
    return f"{start} – {end}"


def build_incident_text(bundle: ContextBundle) -> str:
    """Render the varying incident details into a single user message."""
    rule = bundle.rule
    lines = [
        f"# Fired alert: {rule.title} ({rule.name})",
        f"- Severity (configured): {rule.severity.value}",
        f"- Environment: {rule.env}",
        f"- Condition: `{rule.expr}` {rule.comparator.value} {rule.threshold}",
        f"- Observed value: {bundle.value:g}" if bundle.value is not None else "- Observed value: n/a",
        f"- For-duration: {rule.for_seconds}s",
        f"- Window: {_fmt_window(bundle)}",
    ]
    if bundle.recent_count > 1:
        lines.append(f"- NOTE: this rule has fired {bundle.recent_count} times recently (possible recurring issue).")
    if rule.runbook:
        lines.append(f"\n## Operator runbook hint\n{rule.runbook}")

    if bundle.correlated_metrics:
        lines.append("\n## Correlated metrics")
        for metric in bundle.correlated_metrics:
            lines.append(f"- {metric.summarize()}")

    if bundle.logs:
        lines.append("\n## Recent logs (newest first)")
        lines.append("```")
        lines.extend(bundle.logs[:25])
        lines.append("```")

    lines.append(
        "\nUse the report_analysis tool. Be specific to THIS service and these numbers. "
        "If a known failure mode matches, name it and give its fix commands."
    )
    return "\n".join(lines)


def build_messages(bundle: ContextBundle) -> list[dict]:
    return [{"role": "user", "content": build_incident_text(bundle)}]
