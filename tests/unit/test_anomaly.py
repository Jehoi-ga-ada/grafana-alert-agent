"""Tests for anomaly detection (pure) + config loader + sweeper edges."""

from __future__ import annotations

import pytest

from gaa.anomaly.config_loader import AnomalyConfigError, load_anomaly_checks, parse_checks
from gaa.anomaly.detection import AnomalyConfigError as DetErr
from gaa.anomaly.detection import baseline_query, evaluate_anomaly, with_offset
from gaa.anomaly.models import AnomalyCheck, AnomalyVerdict, Direction
from gaa.anomaly.sweep import AnomalySweeper
from gaa.state.sqlite_store import SqliteStore
from tests.conftest import make_result
from tests.fakes import FakeMetrics, FakeNotifier


def _check(**kw) -> AnomalyCheck:
    data = {"name": "c1", "title": "Check 1", "expr": "m", "factor": 2.0, "direction": "both", "min_baseline": 0.01}
    data.update(kw)
    return AnomalyCheck.model_validate(data)


class TestWithOffset:
    def test_wraps_valid_lookback(self):
        assert with_offset("sum(x)", "1d") == "(sum(x)) offset 1d"

    def test_rejects_bad_lookback(self):
        with pytest.raises(DetErr):
            with_offset("x", "yesterday")

    def test_baseline_query_prefers_explicit(self):
        assert baseline_query(_check(baseline_expr="explicit")) == "explicit"


class TestEvaluateAnomaly:
    def test_above_factor_is_anomalous(self):
        r = evaluate_anomaly(_check(direction="above", factor=2.0), make_result(30.0), make_result(10.0), 1.0)
        assert r.verdict == AnomalyVerdict.ANOMALOUS
        assert r.ratio == 3.0

    def test_within_factor_is_normal(self):
        r = evaluate_anomaly(_check(factor=3.0), make_result(12.0), make_result(10.0), 1.0)
        assert r.verdict == AnomalyVerdict.NORMAL

    def test_below_direction(self):
        r = evaluate_anomaly(_check(direction="below", factor=2.0), make_result(2.0), make_result(10.0), 1.0)
        assert r.verdict == AnomalyVerdict.ANOMALOUS

    def test_small_baseline_skipped(self):
        r = evaluate_anomaly(_check(min_baseline=1.0), make_result(5.0), make_result(0.001), 1.0)
        assert r.verdict == AnomalyVerdict.SKIPPED

    def test_no_data_skipped(self):
        from tests.conftest import empty_result

        r = evaluate_anomaly(_check(), empty_result(), make_result(10.0), 1.0)
        assert r.verdict == AnomalyVerdict.SKIPPED


class TestConfigLoader:
    def test_parses_defaults(self):
        doc = {"defaults": {"factor": 5.0}, "checks": [{"name": "a", "title": "A", "expr": "x"}]}
        checks = parse_checks(doc)
        assert checks[0].factor == 5.0

    def test_rejects_duplicate(self):
        doc = {"checks": [{"name": "a", "title": "A", "expr": "x"}, {"name": "a", "title": "B", "expr": "y"}]}
        with pytest.raises(AnomalyConfigError, match="duplicate"):
            parse_checks(doc)

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_anomaly_checks(tmp_path / "none.yaml") == ()

    def test_loads_shipped_file(self):
        from pathlib import Path

        checks = load_anomaly_checks(Path(__file__).parents[2] / "config" / "anomalies.yaml")
        assert any(c.name == "latency_anomaly" for c in checks)


class TestSweeper:
    @pytest.fixture
    def store(self, tmp_path):
        s = SqliteStore(tmp_path / "s.db")
        yield s
        s.close()

    def _sweeper(self, store, metrics, notifier, interval=900):
        check = _check(name="req", title="Req rate", expr="cur", baseline_expr="base", direction="above", factor=2.0, cooldown=900)
        return AnomalySweeper(checks=(check,), metrics=metrics, notifier=notifier, store=store, clock=lambda: 0.0, interval=interval)

    async def test_edge_trigger_notifies_once(self, store):
        metrics = FakeMetrics({"cur": [30.0], "base": [10.0]})
        notifier = FakeNotifier()
        sweeper = self._sweeper(store, metrics, notifier)
        # First sweep: anomalous → notify
        fired = await sweeper.run_once(now=100.0)
        assert len(fired) == 1 and len(notifier.sent) == 1
        # Second sweep, still anomalous, within cooldown → no new notify
        fired2 = await sweeper.run_once(now=200.0)
        assert fired2 == [] and len(notifier.sent) == 1

    async def test_recovery_message_on_return_to_normal(self, store):
        metrics = FakeMetrics({"cur": [30.0], "base": [10.0]})
        notifier = FakeNotifier()
        sweeper = self._sweeper(store, metrics, notifier)
        await sweeper.run_once(now=100.0)  # anomalous
        metrics.set("cur", [11.0])  # back to normal (1.1×)
        await sweeper.run_once(now=2000.0)
        assert len(notifier.sent) == 2
        assert "cleared" in notifier.sent[1]["embed"]["title"].lower()
