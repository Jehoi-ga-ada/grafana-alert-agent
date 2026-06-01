"""Tests for pure notification/dedup decisions."""

from __future__ import annotations

from gaa.domain.dedup import (
    NotificationKind,
    decide_notification,
    mark_notified,
)
from gaa.domain.models import AlertStatus, RuleState
from tests.conftest import make_rule


def _state(status: AlertStatus, **kw) -> RuleState:
    return RuleState(name="test_rule", status=status, **kw)


class TestDecideNotification:
    def test_notifies_on_entering_firing(self):
        prev = _state(AlertStatus.PENDING)
        new = _state(AlertStatus.FIRING, firing_since=100.0)
        decision = decide_notification(prev, new, make_rule(), now=100.0)
        assert decision.kind == NotificationKind.FIRING

    def test_notifies_on_resolve(self):
        prev = _state(AlertStatus.FIRING)
        new = _state(AlertStatus.RESOLVED)
        decision = decide_notification(prev, new, make_rule(), now=200.0)
        assert decision.kind == NotificationKind.RESOLVED

    def test_no_notification_while_staying_firing(self):
        prev = _state(AlertStatus.FIRING)
        new = _state(AlertStatus.FIRING)
        decision = decide_notification(prev, new, make_rule(), now=200.0)
        assert decision.should_notify is False

    def test_cooldown_suppresses_refire(self):
        # Arrange: last notified 60s ago, cooldown 900s
        prev = _state(AlertStatus.INACTIVE)
        new = _state(AlertStatus.FIRING, last_notified_at=140.0)
        rule = make_rule(cooldown=900)
        # Act
        decision = decide_notification(prev, new, rule, now=200.0)
        # Assert
        assert decision.should_notify is False
        assert "cooldown" in decision.reason

    def test_refire_allowed_after_cooldown(self):
        prev = _state(AlertStatus.INACTIVE)
        new = _state(AlertStatus.FIRING, last_notified_at=100.0)
        rule = make_rule(cooldown=900)
        decision = decide_notification(prev, new, rule, now=1100.0)
        assert decision.kind == NotificationKind.FIRING


class TestMarkNotified:
    def test_stamps_notification_time_without_mutating(self):
        original = _state(AlertStatus.FIRING)
        stamped = mark_notified(original, now=555.0)
        assert stamped.last_notified_at == 555.0
        assert original.last_notified_at is None  # immutability preserved
