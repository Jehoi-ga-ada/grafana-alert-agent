"""Tests for the pure health evaluation + status embed."""

from __future__ import annotations

from gaa.domain.models import Comparator, Severity
from gaa.notify.embed import build_status_embed
from gaa.status.health import evaluate_health
from gaa.status.models import Verdict
from tests.conftest import empty_result, make_result, make_rule


def _rules():
    return (
        make_rule(name="app_down", title="App down", expr="up", comparator=Comparator.EQ, threshold=0, severity=Severity.CRITICAL),
        make_rule(name="cpu", title="CPU", comparator=Comparator.GT, threshold=85, severity=Severity.WARNING),
    )


class TestEvaluateHealth:
    def test_all_ok(self):
        rules = _rules()
        results = {"app_down": make_result(1.0), "cpu": make_result(20.0)}
        report = evaluate_health(rules, results, now=100.0)
        assert report.overall == Verdict.OK
        assert all(h.verdict == Verdict.OK for h in report.rules)

    def test_critical_breach_makes_overall_crit(self):
        rules = _rules()
        results = {"app_down": make_result(0.0), "cpu": make_result(20.0)}
        report = evaluate_health(rules, results, now=100.0)
        assert report.overall == Verdict.CRIT

    def test_warning_breach_is_warn(self):
        rules = _rules()
        results = {"app_down": make_result(1.0), "cpu": make_result(95.0)}
        report = evaluate_health(rules, results, now=100.0)
        assert report.overall == Verdict.WARN

    def test_missing_data_is_unknown(self):
        rules = _rules()
        results = {"app_down": empty_result(), "cpu": empty_result()}
        report = evaluate_health(rules, results, now=100.0)
        assert report.overall == Verdict.UNKNOWN
        assert all(h.verdict == Verdict.UNKNOWN for h in report.rules)

    def test_crit_wins_over_warn(self):
        rules = _rules()
        results = {"app_down": make_result(0.0), "cpu": make_result(95.0)}
        assert evaluate_health(rules, results, 1.0).overall == Verdict.CRIT


class TestGatherHealth:
    async def test_gathers_and_evaluates(self):
        from gaa.status.service import gather_health
        from tests.fakes import FakeMetrics

        rules = (
            make_rule(name="cpu", title="CPU", expr="cpu_expr", comparator=Comparator.GT, threshold=85, severity=Severity.WARNING),
        )
        metrics = FakeMetrics({"cpu_expr": [95.0]})
        report = await gather_health(metrics, rules, now=100.0)
        assert report.overall == Verdict.WARN

    async def test_query_error_is_unknown(self):
        from gaa.status.service import gather_health

        class Boom:
            async def query_instant(self, q):
                raise RuntimeError("down")

        rules = (make_rule(name="cpu", title="CPU", expr="x"),)
        report = await gather_health(Boom(), rules, now=1.0)
        assert report.overall == Verdict.UNKNOWN


class TestStatusEmbed:
    def test_embed_reflects_overall(self):
        rules = _rules()
        results = {"app_down": make_result(0.0), "cpu": make_result(20.0)}
        report = evaluate_health(rules, results, now=100.0)
        embed = build_status_embed(report)
        assert "CRIT" in embed["title"]
        assert "🔴" in embed["title"]
        assert "App down" in embed["description"]
