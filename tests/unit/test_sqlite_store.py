"""Tests for the SQLite state store."""

from __future__ import annotations

import pytest

from gaa.domain.models import AlertStatus, Incident, RuleState, Severity, TimeWindow
from gaa.state.sqlite_store import SqliteStore


@pytest.fixture
def store(tmp_path):
    s = SqliteStore(tmp_path / "state.db")
    yield s
    s.close()


class TestRuleState:
    async def test_put_then_get_roundtrips(self, store):
        state = RuleState(
            name="r1",
            status=AlertStatus.FIRING,
            condition_since=10.0,
            firing_since=20.0,
            last_value=9.5,
            window=TimeWindow(1.0, 2.0),
        )
        await store.put_state(state)
        loaded = await store.get_state("r1")
        assert loaded == state

    async def test_get_missing_returns_none(self, store):
        assert await store.get_state("nope") is None

    async def test_put_upserts(self, store):
        await store.put_state(RuleState(name="r1", status=AlertStatus.PENDING))
        await store.put_state(RuleState(name="r1", status=AlertStatus.FIRING))
        loaded = await store.get_state("r1")
        assert loaded.status == AlertStatus.FIRING
        assert len(await store.list_states()) == 1


class TestIncidents:
    async def test_record_and_fetch_with_screenshot(self, store):
        incident = Incident(
            rule_name="high_cpu",
            title="CPU",
            severity=Severity.WARNING,
            fired_at=100.0,
            value=92.0,
            summary="cpu hot",
            remediation=("check load", "scale up"),
        )
        iid = await store.record_incident(incident, screenshot=b"\x89PNG")
        fetched = await store.get_incident(iid)
        assert fetched.title == "CPU"
        assert fetched.remediation == ("check load", "scale up")
        assert fetched.has_screenshot is True
        assert await store.get_screenshot(iid) == b"\x89PNG"

    async def test_resolve_sets_timestamp(self, store):
        iid = await store.record_incident(
            Incident(rule_name="r", title="t", severity=Severity.HIGH, fired_at=1.0)
        )
        await store.resolve_incident(iid, resolved_at=50.0)
        assert (await store.get_incident(iid)).resolved_at == 50.0

    async def test_list_orders_newest_first(self, store):
        for ts in (1.0, 3.0, 2.0):
            await store.record_incident(
                Incident(rule_name="r", title="t", severity=Severity.HIGH, fired_at=ts)
            )
        incidents = await store.list_incidents()
        assert [i.fired_at for i in incidents] == [3.0, 2.0, 1.0]

    async def test_incident_thread_roundtrip(self, store):
        iid = await store.record_incident(
            Incident(rule_name="r", title="t", severity=Severity.HIGH, fired_at=1.0)
        )
        await store.set_incident_thread(iid, "thread-123")
        found = await store.get_incident_by_thread("thread-123")
        assert found is not None and found.id == iid
        assert found.thread_id == "thread-123"
        assert await store.get_incident_by_thread("missing") is None

    async def test_count_recent(self, store):
        for ts in (10.0, 20.0, 200.0):
            await store.record_incident(
                Incident(rule_name="r", title="t", severity=Severity.HIGH, fired_at=ts)
            )
        assert await store.count_recent("r", since=15.0) == 2
