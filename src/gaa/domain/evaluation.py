"""Pure rule evaluation: (rule, query result, prev state, now) -> new state.

No I/O, no clock access — `now` is injected. This is the most heavily tested
module and the core of the agent's correctness.
"""

from __future__ import annotations

from gaa.config.rule_models import Rule
from gaa.domain.models import (
    AlertStatus,
    Comparator,
    QueryResult,
    RuleState,
    Sample,
    TimeWindow,
)

# Padding added before the firing window so the screenshot shows lead-up context.
_WINDOW_PAD_SECONDS = 300
_MIN_WINDOW_SECONDS = 900


def breaches(value: float, comparator: Comparator, threshold: float) -> bool:
    """Whether a single value violates the threshold under the comparator."""
    match comparator:
        case Comparator.GT:
            return value > threshold
        case Comparator.GTE:
            return value >= threshold
        case Comparator.LT:
            return value < threshold
        case Comparator.LTE:
            return value <= threshold
        case Comparator.EQ:
            return value == threshold
        case Comparator.NE:
            return value != threshold
    raise ValueError(f"unknown comparator: {comparator}")  # pragma: no cover


def _representative(result: QueryResult, rule: Rule) -> tuple[bool, float | None]:
    """Return (any_series_breaches, representative_value).

    Fires if ANY series breaches (so `up == 0` fires when any instance is down).
    The representative value is the most extreme breaching series for the comparator.
    """
    breaching: list[Sample] = [
        s for s in result.samples if breaches(s.value, rule.comparator, rule.threshold)
    ]
    if not breaching:
        return False, None
    if rule.comparator in (Comparator.LT, Comparator.LTE):
        value = min(s.value for s in breaching)
    elif rule.comparator in (Comparator.GT, Comparator.GTE):
        value = max(s.value for s in breaching)
    else:  # EQ / NE — value is unambiguous
        value = breaching[0].value
    return True, value


def _firing_window(rule: Rule, now: float) -> TimeWindow:
    span = max(rule.for_seconds + _WINDOW_PAD_SECONDS, _MIN_WINDOW_SECONDS)
    return TimeWindow(start=now - span, end=now)


def evaluate_rule(
    rule: Rule,
    result: QueryResult,
    prev: RuleState | None,
    now: float,
) -> RuleState:
    """Compute the new rule state. Pure.

    No-data (empty result) holds the previous state — absence of data is never
    treated as resolved (FR1).
    """
    prev = prev or RuleState.initial(rule.name)

    if result.is_empty:
        return prev

    is_breaching, value = _representative(result, rule)

    if is_breaching:
        return _advance_active(rule, prev, value, now)
    return _advance_clear(rule, prev, value, now)


def _advance_active(rule: Rule, prev: RuleState, value: float | None, now: float) -> RuleState:
    condition_since = prev.condition_since if prev.status in (
        AlertStatus.PENDING,
        AlertStatus.FIRING,
    ) else now

    held_for = now - condition_since
    if prev.status == AlertStatus.FIRING:
        return RuleState(
            name=rule.name,
            status=AlertStatus.FIRING,
            condition_since=condition_since,
            firing_since=prev.firing_since,
            last_value=value,
            last_notified_at=prev.last_notified_at,
            window=prev.window,
        )

    if held_for >= rule.for_seconds:
        return RuleState(
            name=rule.name,
            status=AlertStatus.FIRING,
            condition_since=condition_since,
            firing_since=now,
            last_value=value,
            last_notified_at=prev.last_notified_at,
            window=_firing_window(rule, now),
        )

    return RuleState(
        name=rule.name,
        status=AlertStatus.PENDING,
        condition_since=condition_since,
        firing_since=None,
        last_value=value,
        last_notified_at=prev.last_notified_at,
        window=None,
    )


def _advance_clear(rule: Rule, prev: RuleState, value: float | None, now: float) -> RuleState:
    if prev.status == AlertStatus.FIRING:
        return RuleState(
            name=rule.name,
            status=AlertStatus.RESOLVED,
            condition_since=None,
            firing_since=prev.firing_since,
            last_value=value,
            last_notified_at=prev.last_notified_at,
            window=prev.window,
        )
    return RuleState(
        name=rule.name,
        status=AlertStatus.INACTIVE,
        condition_since=None,
        firing_since=None,
        last_value=value,
        last_notified_at=prev.last_notified_at,
        window=None,
    )
