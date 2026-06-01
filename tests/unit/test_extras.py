"""Tests for compare, report markdown, and digest embed."""

from __future__ import annotations

from gaa.compare import compute_comparison, format_comparison, resolve_metric
from gaa.domain.models import Incident, Severity
from gaa.notify.embed import build_digest_embed
from gaa.report.markdown import render_report_markdown
from gaa.status.models import HealthReport, Verdict
from tests.conftest import empty_result, make_result


class TestCompare:
    def test_resolve_alias(self):
        assert "quantile" in resolve_metric("p99")

    def test_resolve_passthrough(self):
        assert resolve_metric("sum(up)") == "sum(up)"

    def test_compute_delta_up(self):
        cmp = compute_comparison(make_result(15.0), make_result(10.0))
        assert round(cmp["delta_pct"], 1) == 50.0
        assert cmp["arrow"] == "▲"

    def test_compute_no_baseline(self):
        cmp = compute_comparison(make_result(15.0), empty_result())
        assert cmp["delta_pct"] is None

    def test_format_includes_delta(self):
        out = format_comparison("p99", "1d", compute_comparison(make_result(15.0), make_result(10.0)))
        assert "p99" in out and "%" in out


class TestReportMarkdown:
    def test_renders_sections(self):
        inc = Incident(
            id=7, rule_name="high_error_rate", title="High error rate", severity=Severity.CRITICAL,
            fired_at=1_700_000_000.0, value=30.0, summary="db down", likely_cause="pg gone",
            remediation=("restart pg",), dashboard_url="https://g/d/x",
        )
        md = render_report_markdown(inc, "Investigation body here.", ["query_prometheus", "find_slow_requests"])
        assert "# Incident Report — High error rate" in md
        assert "Investigation body here." in md
        assert "restart pg" in md
        assert "query_prometheus" in md
        assert "https://g/d/x" in md


class TestDigestEmbed:
    def test_digest_summarizes(self):
        report = HealthReport(rules=(), overall=Verdict.WARN, at=1.0)
        inc = Incident(id=1, rule_name="r", title="App down", severity=Severity.CRITICAL, fired_at=1.0)
        embed = build_digest_embed(report, [inc], [], iso_timestamp="2026-06-01T00:00:00+00:00")
        assert "WARN" in embed["title"]
        assert "1 incident" in embed["description"]
        assert any("App down" in f["value"] for f in embed["fields"])
