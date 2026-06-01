"""End-to-end pipeline + daemon flow with fakes and a real SQLite store."""

from __future__ import annotations

import pytest

from gaa.analyzer.models import AnalysisResult
from gaa.domain.models import AlertStatus, Comparator
from gaa.enrichment.enricher import Enricher
from gaa.orchestrator.daemon import Daemon
from gaa.orchestrator.pipeline import AlertPipeline
from gaa.state.sqlite_store import SqliteStore
from tests.conftest import make_rule
from tests.fakes import FakeAnalyzer, FakeCapturer, FakeLogs, FakeMetrics, FakeNotifier

_ANALYSIS = AnalysisResult(
    summary="boom", likely_cause="db", remediation=("restart",), severity="critical", confidence="high"
)


class Harness:
    def __init__(self, tmp_path, *, capturer_png=b"PNG", panel_id=8):
        self.store = SqliteStore(tmp_path / "s.db")
        self.metrics = FakeMetrics()
        self.notifier = FakeNotifier()
        self.capturer = FakeCapturer(capturer_png)
        self.analyzer = FakeAnalyzer(_ANALYSIS)
        self.enricher = Enricher(self.metrics, FakeLogs())
        self.pipeline = AlertPipeline(
            enricher=self.enricher,
            analyzer=self.analyzer,
            capturer=self.capturer,
            notifier=self.notifier,
            store=self.store,
            grafana_base_url="https://g.test",
            dashboard_uid="uid",
            dashboard_slug="dash",
        )
        self.rule = make_rule(name="r", expr="metric", comparator=Comparator.GT, threshold=5, panel_id=panel_id)
        self.clock_value = 100.0
        self.daemon = Daemon(
            rules=(self.rule,),
            metrics=self.metrics,
            store=self.store,
            pipeline=self.pipeline,
            clock=lambda: self.clock_value,
            poll_interval=1.0,
        )

    def close(self):
        self.store.close()


@pytest.fixture
def harness(tmp_path):
    h = Harness(tmp_path)
    yield h
    h.close()


async def test_firing_sends_alert_with_screenshot_and_records_incident(harness):
    # Arrange: metric breaching
    harness.metrics.set("metric", [9.0])
    # Act
    report = await harness.daemon.run_once(now=100.0)
    # Assert
    assert report.fired == ["r"]
    assert len(harness.notifier.sent) == 1
    assert harness.notifier.sent[0]["image"] == b"PNG"  # screenshot attached
    incidents = await harness.store.list_incidents()
    assert incidents[0].rule_name == "r"
    assert incidents[0].is_open
    state = await harness.store.get_state("r")
    assert state.status == AlertStatus.FIRING
    assert state.last_notified_at == 100.0


async def test_resolve_sends_recovery_and_closes_incident(harness):
    # Arrange: fire, then clear
    harness.metrics.set("metric", [9.0])
    await harness.daemon.run_once(now=100.0)
    harness.metrics.set("metric", [1.0])
    # Act
    report = await harness.daemon.run_once(now=260.0)
    # Assert
    assert report.resolved == ["r"]
    assert len(harness.notifier.sent) == 2
    assert "Resolved" in harness.notifier.sent[1]["embed"]["title"]
    incidents = await harness.store.list_incidents()
    assert incidents[0].resolved_at == 260.0
    assert (await harness.store.get_state("r")).status == AlertStatus.INACTIVE


async def test_no_data_does_not_resolve(harness):
    harness.metrics.set("metric", [9.0])
    await harness.daemon.run_once(now=100.0)
    harness.metrics.set("metric", [])  # query returns nothing
    report = await harness.daemon.run_once(now=200.0)
    assert report.resolved == []
    assert (await harness.store.get_state("r")).status == AlertStatus.FIRING


async def test_query_error_skips_rule_without_transition(harness):
    async def boom(_promql):
        raise RuntimeError("VM down")

    harness.metrics.query_instant = boom  # type: ignore[assignment]
    report = await harness.daemon.run_once(now=100.0)
    assert report.errors == ["r"]
    assert report.fired == []


async def test_screenshot_failure_still_notifies(tmp_path):
    h = Harness(tmp_path, capturer_png=None)
    try:
        h.metrics.set("metric", [9.0])
        report = await h.daemon.run_once(now=100.0)
        assert report.fired == ["r"]
        assert h.notifier.sent[0]["image"] is None  # degraded, but still sent
    finally:
        h.close()


class _GatewayNotifier:
    """Fake gateway: supports post_alert + returns a thread id."""

    def __init__(self):
        self.alerts = []

    async def post_alert(self, *, embed, image_png, image_name, thread_name):
        self.alerts.append(thread_name)
        return "thread-99"

    async def send(self, *, embed, image_png=None, image_name="p.png"):
        raise AssertionError("send should not be called when post_alert exists")


async def test_firing_opens_incident_thread(tmp_path):
    h = Harness(tmp_path)
    try:
        gateway = _GatewayNotifier()
        h.pipeline._notifier = gateway  # swap to a gateway-style notifier
        h.metrics.set("metric", [9.0])
        await h.daemon.run_once(now=100.0)
        # incident got a thread id stored
        incidents = await h.store.list_incidents()
        assert incidents[0].thread_id == "thread-99"
        assert gateway.alerts and gateway.alerts[0].startswith("#")
    finally:
        h.close()


async def test_cooldown_blocks_immediate_refire(harness):
    # fire
    harness.metrics.set("metric", [9.0])
    await harness.daemon.run_once(now=100.0)
    # clear -> resolved (back to inactive)
    harness.metrics.set("metric", [1.0])
    await harness.daemon.run_once(now=160.0)
    # breach again within cooldown (default 900s)
    harness.metrics.set("metric", [9.0])
    report = await harness.daemon.run_once(now=200.0)
    assert report.fired == []  # suppressed by cooldown
