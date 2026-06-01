"""Tests for the pure rule-evaluation core."""

from __future__ import annotations

from gaa.domain.evaluation import breaches, evaluate_rule
from gaa.domain.models import AlertStatus, Comparator, RuleState
from tests.conftest import empty_result, make_result, make_rule


class TestBreaches:
    def test_gt_above_threshold_breaches(self):
        assert breaches(6.0, Comparator.GT, 5.0) is True

    def test_gt_at_threshold_does_not_breach(self):
        assert breaches(5.0, Comparator.GT, 5.0) is False

    def test_lt_below_threshold_breaches(self):
        assert breaches(3.0, Comparator.LT, 10.0) is True

    def test_eq_matches_threshold(self):
        assert breaches(0.0, Comparator.EQ, 0.0) is True

    def test_ne_differs_from_threshold(self):
        assert breaches(1.0, Comparator.NE, 0.0) is True


class TestEvaluateRuleImmediate:
    def test_fires_immediately_when_for_is_zero(self):
        # Arrange
        rule = make_rule(comparator=Comparator.GT, threshold=5, **{"for": 0})
        # Act
        state = evaluate_rule(rule, make_result(7.0), None, now=100.0)
        # Assert
        assert state.status == AlertStatus.FIRING
        assert state.last_value == 7.0
        assert state.window is not None

    def test_inactive_when_not_breaching(self):
        rule = make_rule(comparator=Comparator.GT, threshold=5)
        state = evaluate_rule(rule, make_result(1.0), None, now=100.0)
        assert state.status == AlertStatus.INACTIVE

    def test_any_series_down_fires_for_up_eq_zero(self):
        # Arrange: app_down-style rule, one instance up, one down
        rule = make_rule(expr="up", comparator=Comparator.EQ, threshold=0)
        result = make_result(1.0, 0.0)
        # Act
        state = evaluate_rule(rule, result, None, now=10.0)
        # Assert
        assert state.status == AlertStatus.FIRING


class TestForDuration:
    def test_pending_before_for_duration_met(self):
        rule = make_rule(comparator=Comparator.GT, threshold=5, **{"for": 300})
        state = evaluate_rule(rule, make_result(9.0), None, now=1000.0)
        assert state.status == AlertStatus.PENDING
        assert state.condition_since == 1000.0
        assert state.window is None

    def test_promotes_to_firing_once_for_duration_elapses(self):
        # Arrange
        rule = make_rule(comparator=Comparator.GT, threshold=5, **{"for": 300})
        pending = evaluate_rule(rule, make_result(9.0), None, now=1000.0)
        # Act: still breaching 301s later
        firing = evaluate_rule(rule, make_result(9.0), pending, now=1301.0)
        # Assert
        assert firing.status == AlertStatus.FIRING
        assert firing.firing_since == 1301.0
        assert firing.condition_since == 1000.0

    def test_pending_resets_when_condition_clears(self):
        rule = make_rule(comparator=Comparator.GT, threshold=5, **{"for": 300})
        pending = evaluate_rule(rule, make_result(9.0), None, now=1000.0)
        cleared = evaluate_rule(rule, make_result(1.0), pending, now=1100.0)
        assert cleared.status == AlertStatus.INACTIVE
        assert cleared.condition_since is None


class TestResolveAndNoData:
    def test_firing_to_resolved_on_clear(self):
        rule = make_rule(comparator=Comparator.GT, threshold=5)
        firing = evaluate_rule(rule, make_result(9.0), None, now=10.0)
        resolved = evaluate_rule(rule, make_result(1.0), firing, now=20.0)
        assert resolved.status == AlertStatus.RESOLVED
        assert resolved.firing_since == firing.firing_since

    def test_empty_result_holds_previous_firing_state(self):
        # FR1: absence of data must never resolve an alert
        rule = make_rule(comparator=Comparator.GT, threshold=5)
        firing = evaluate_rule(rule, make_result(9.0), None, now=10.0)
        held = evaluate_rule(rule, empty_result(), firing, now=20.0)
        assert held.status == AlertStatus.FIRING

    def test_empty_result_with_no_prev_is_inactive(self):
        rule = make_rule()
        state = evaluate_rule(rule, empty_result(), None, now=10.0)
        assert state.status == AlertStatus.INACTIVE

    def test_firing_stays_firing_while_breaching(self):
        rule = make_rule(comparator=Comparator.GT, threshold=5)
        first = evaluate_rule(rule, make_result(9.0), None, now=10.0)
        second = evaluate_rule(rule, make_result(8.0), first, now=40.0)
        assert second.status == AlertStatus.FIRING
        assert second.firing_since == first.firing_since
        assert second.last_value == 8.0
