"""Tests for pure Discord embed builders."""

from __future__ import annotations

from gaa.analyzer.models import AnalysisResult
from gaa.domain.models import SEVERITY_COLORS, Severity
from gaa.notify.embed import build_firing_embed, build_heartbeat_embed, build_resolved_embed
from tests.conftest import make_rule

_ANALYSIS = AnalysisResult(
    summary="Postgres is unreachable; 5xx rate at 30%.",
    likely_cause="DB connection refused on the stateful host.",
    remediation=("aws ssm start-session --target i-xxx", "systemctl status postgresql"),
    severity="critical",
    confidence="high",
)


class TestFiringEmbed:
    def test_carries_severity_color_and_title(self):
        rule = make_rule(title="High error rate", severity=Severity.CRITICAL)
        embed = build_firing_embed(rule, _ANALYSIS, 30.0, "https://g/d/x", recent_count=1)
        assert embed["color"] == SEVERITY_COLORS[Severity.CRITICAL]
        assert "High error rate" in embed["title"]
        assert embed["url"] == "https://g/d/x"

    def test_includes_cause_and_numbered_remediation(self):
        embed = build_firing_embed(make_rule(), _ANALYSIS, 30.0, "")
        fix_field = next(f for f in embed["fields"] if "fix" in f["name"].lower())
        assert "1. aws ssm" in fix_field["value"]
        assert "2. systemctl" in fix_field["value"]

    def test_recurrence_field_only_when_repeated(self):
        embed = build_firing_embed(make_rule(), _ANALYSIS, 1.0, "", recent_count=4)
        assert any("Recurrence" in f["name"] for f in embed["fields"])
        embed_once = build_firing_embed(make_rule(), _ANALYSIS, 1.0, "", recent_count=1)
        assert not any("Recurrence" in f["name"] for f in embed_once["fields"])

    def test_degraded_analysis_notes_in_footer(self):
        degraded = AnalysisResult.fallback("something happened")
        embed = build_firing_embed(make_rule(), degraded, 1.0, "")
        assert "unavailable" in embed["footer"]["text"]

    def test_field_values_are_truncated(self):
        huge = AnalysisResult(summary="x", likely_cause="y" * 5000, remediation=(), severity="", confidence="")
        embed = build_firing_embed(make_rule(), huge, 1.0, "")
        cause = next(f for f in embed["fields"] if "cause" in f["name"].lower())
        assert len(cause["value"]) <= 1024


class TestResolvedAndHeartbeat:
    def test_resolved_embed_reports_duration(self):
        embed = build_resolved_embed(make_rule(title="CPU"), duration_seconds=3661)
        assert "Resolved" in embed["title"]
        assert "1h1m" in embed["description"]

    def test_heartbeat_reports_active_count(self):
        embed = build_heartbeat_embed(active_alerts=2)
        assert "2 active" in embed["description"]
