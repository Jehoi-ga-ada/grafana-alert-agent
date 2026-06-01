"""Pure Discord embed builders. No I/O — easy to snapshot-test."""

from __future__ import annotations

from gaa.analyzer.models import AnalysisResult
from gaa.config.rule_models import Rule
from gaa.domain.models import RESOLVED_COLOR, SEVERITY_COLORS, Severity

_FIELD_LIMIT = 1024
_DESC_LIMIT = 4096

_SEVERITY_EMOJI = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH: "🟠",
    Severity.WARNING: "🟡",
    Severity.INFO: "🟢",
}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _remediation_block(steps: tuple[str, ...]) -> str:
    if not steps:
        return "_No automatic suggestions — investigate using the metrics/logs._"
    return "\n".join(f"{i}. {step}" for i, step in enumerate(steps, start=1))


def build_firing_embed(
    rule: Rule,
    analysis: AnalysisResult,
    value: float | None,
    dashboard_url: str,
    recent_count: int = 0,
    iso_timestamp: str | None = None,
) -> dict:
    """Build the rich embed for a firing alert."""
    emoji = _SEVERITY_EMOJI.get(rule.severity, "⚠️")
    fields = [
        {"name": "🔎 Likely cause", "value": _truncate(analysis.likely_cause or "Unknown", _FIELD_LIMIT)},
        {"name": "🛠️ Suggested fix", "value": _truncate(_remediation_block(analysis.remediation), _FIELD_LIMIT)},
        {"name": "Observed", "value": f"`{value:g}`" if value is not None else "n/a", "inline": True},
        {"name": "Severity", "value": rule.severity.value, "inline": True},
        {"name": "Confidence", "value": analysis.confidence or "n/a", "inline": True},
    ]
    if recent_count > 1:
        fields.append({"name": "Recurrence", "value": f"{recent_count}× recently", "inline": True})

    footer = f"Grafana Alert Agent • {rule.env}"
    if analysis.degraded:
        footer += " • AI analysis unavailable"

    embed: dict = {
        "title": _truncate(f"{emoji} {rule.title}", 256),
        "description": _truncate(analysis.summary or rule.title, _DESC_LIMIT),
        "color": SEVERITY_COLORS.get(rule.severity, 0x808080),
        "fields": fields,
        "footer": {"text": footer},
    }
    if dashboard_url:
        embed["url"] = dashboard_url
    if iso_timestamp:
        embed["timestamp"] = iso_timestamp
    return embed


def build_resolved_embed(
    rule: Rule,
    duration_seconds: float | None = None,
    iso_timestamp: str | None = None,
) -> dict:
    """Build the embed sent when an alert clears."""
    description = f"**{rule.title}** has recovered."
    if duration_seconds is not None:
        description += f" Open for {_human_duration(duration_seconds)}."
    embed: dict = {
        "title": _truncate(f"✅ Resolved: {rule.title}", 256),
        "description": description,
        "color": RESOLVED_COLOR,
        "footer": {"text": f"Grafana Alert Agent • {rule.env}"},
    }
    if iso_timestamp:
        embed["timestamp"] = iso_timestamp
    return embed


def build_heartbeat_embed(active_alerts: int, iso_timestamp: str | None = None) -> dict:
    return {
        "title": "💓 Agent heartbeat",
        "description": f"Polling normally. {active_alerts} active alert(s).",
        "color": 0x5865F2,
        "footer": {"text": "Grafana Alert Agent"},
        **({"timestamp": iso_timestamp} if iso_timestamp else {}),
    }


_VERDICT_EMOJI = {"ok": "🟢", "warn": "🟡", "crit": "🔴", "unknown": "⚪"}
_VERDICT_COLOR = {"ok": 0x2EB67D, "warn": 0xECB22E, "crit": 0xE01E5A, "unknown": 0x808080}


def build_status_embed(report, iso_timestamp: str | None = None) -> dict:
    """Render a HealthReport (status.models) into a Discord embed."""
    overall = report.overall.value
    lines = []
    for h in report.rules:
        value = f"`{h.value:g}`" if h.value is not None else "—"
        lines.append(f"{_VERDICT_EMOJI.get(h.verdict.value, '⚪')} **{h.title}** · {value}")
    embed: dict = {
        "title": f"{_VERDICT_EMOJI.get(overall, '⚪')} System status: {overall.upper()}",
        "description": "\n".join(lines) or "no rules configured",
        "color": _VERDICT_COLOR.get(overall, 0x808080),
        "footer": {"text": "Grafana Alert Agent · point-in-time check"},
    }
    if iso_timestamp:
        embed["timestamp"] = iso_timestamp
    return embed


def build_anomaly_embed(result, kind: str = "alert", iso_timestamp: str | None = None) -> dict:
    """Render an AnomalyResult (anomaly.models) into a Discord embed."""
    if kind == "recovery":
        embed: dict = {
            "title": f"✅ Anomaly cleared: {result.title}",
            "description": f"**{result.title}** is back within normal range.",
            "color": RESOLVED_COLOR,
            "footer": {"text": "Grafana Alert Agent · anomaly"},
        }
    else:
        fields = [
            {"name": "Now", "value": f"`{result.current:g}`" if result.current is not None else "—", "inline": True},
            {"name": "Baseline", "value": f"`{result.baseline:g}`" if result.baseline is not None else "—", "inline": True},
            {"name": "Ratio", "value": f"`{result.ratio:.2f}×`" if result.ratio is not None else "—", "inline": True},
        ]
        embed = {
            "title": f"📈 Anomaly detected: {result.title}",
            "description": result.reason or "Deviation from the historical baseline.",
            "color": 0xED8F1C,
            "fields": fields,
            "footer": {"text": "Grafana Alert Agent · anomaly"},
        }
    if iso_timestamp:
        embed["timestamp"] = iso_timestamp
    return embed


def build_digest_embed(report, incidents: list, anomalies: list, iso_timestamp: str | None = None) -> dict:
    """Daily digest: overall health + 24h incidents + current anomalies."""
    overall = report.overall.value if report is not None else "unknown"
    inc_lines = "\n".join(
        f"• `#{i.id}` {i.title} ({'open' if i.is_open else 'resolved'})" for i in incidents[:10]
    ) or "none"
    anom_lines = "\n".join(f"• {a.title} — {a.reason}" for a in anomalies[:10]) or "none"
    return {
        "title": f"🗒️ Daily digest — {_VERDICT_EMOJI.get(overall, '⚪')} {overall.upper()}",
        "description": (
            f"Health: **{overall.upper()}** · {len(incidents)} incident(s) in 24h · "
            f"{len(anomalies)} anomaly(ies) now."
        ),
        "color": _VERDICT_COLOR.get(overall, 0x5865F2),
        "fields": [
            {"name": "Incidents (24h)", "value": _truncate(inc_lines, _FIELD_LIMIT)},
            {"name": "Anomalies", "value": _truncate(anom_lines, _FIELD_LIMIT)},
        ],
        "footer": {"text": "Grafana Alert Agent · digest"},
        **({"timestamp": iso_timestamp} if iso_timestamp else {}),
    }


def _human_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h{(seconds % 3600) // 60}m"
