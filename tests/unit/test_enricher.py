"""Tests for context enrichment."""

from __future__ import annotations

from gaa.domain.models import TimeWindow
from gaa.enrichment.enricher import Enricher
from tests.conftest import make_rule
from tests.fakes import FakeLogs, FakeMetrics


async def test_enrich_gathers_correlated_metrics_and_logs():
    # Arrange
    rule = make_rule(
        correlations={
            "metrics": {"goroutines": "go_goroutines", "rate": "sum(rate(x[1m]))"},
            "logs": {"errs": '{team="g"}'},
        }
    )
    metrics = FakeMetrics({"go_goroutines": [1500.0], "sum(rate(x[1m]))": [42.0]})
    logs = FakeLogs(lines=("err: boom", "err: again"))
    enricher = Enricher(metrics, logs)

    # Act
    bundle = await enricher.enrich(rule, value=9.0, window=TimeWindow(0, 100), recent_count=3)

    # Assert
    labels = {m.label for m in bundle.correlated_metrics}
    assert labels == {"goroutines", "rate"}
    assert bundle.logs == ("err: boom", "err: again")
    assert bundle.recent_count == 3


async def test_enrich_tolerates_no_correlations():
    rule = make_rule()
    bundle = await Enricher(FakeMetrics(), FakeLogs()).enrich(rule, 1.0, TimeWindow(0, 1))
    assert bundle.correlated_metrics == ()
    assert bundle.logs == ()


async def test_correlated_metric_summarize_handles_empty():
    rule = make_rule(correlations={"metrics": {"missing": "absent_metric"}})
    bundle = await Enricher(FakeMetrics(), FakeLogs()).enrich(rule, 1.0, TimeWindow(0, 1))
    assert "no data" in bundle.correlated_metrics[0].summarize()
