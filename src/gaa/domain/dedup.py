"""Pure notification decisions: cooldown, flapping, resolve.

Given the previous and freshly-evaluated rule state plus the clock, decide
whether to send a Discord notification and of which kind. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from gaa.config.rule_models import Rule
from gaa.domain.models import AlertStatus, RuleState


class NotificationKind(StrEnum):
    FIRING = "firing"
    RESOLVED = "resolved"


@dataclass(frozen=True, slots=True)
class NotificationDecision:
    kind: NotificationKind | None
    reason: str

    @property
    def should_notify(self) -> bool:
        return self.kind is not None


_NO_OP = NotificationDecision(kind=None, reason="no transition")


def decide_notification(
    prev: RuleState,
    new: RuleState,
    rule: Rule,
    now: float,
) -> NotificationDecision:
    """Decide whether a transition warrants a Discord message.

    Notify on the edge into FIRING (subject to per-rule cooldown to damp
    flapping) and on the edge out of FIRING into RESOLVED.
    """
    entered_firing = new.status == AlertStatus.FIRING and prev.status != AlertStatus.FIRING
    if entered_firing:
        if _in_cooldown(new.last_notified_at, rule.cooldown, now):
            return NotificationDecision(kind=None, reason="within cooldown window")
        return NotificationDecision(kind=NotificationKind.FIRING, reason="entered firing")

    if new.status == AlertStatus.RESOLVED and prev.status == AlertStatus.FIRING:
        return NotificationDecision(kind=NotificationKind.RESOLVED, reason="cleared")

    return _NO_OP


def _in_cooldown(last_notified_at: float | None, cooldown: int, now: float) -> bool:
    if last_notified_at is None or cooldown <= 0:
        return False
    return (now - last_notified_at) < cooldown


def mark_notified(state: RuleState, now: float) -> RuleState:
    """Return a copy of the state stamped with the notification time."""
    return RuleState(
        name=state.name,
        status=state.status,
        condition_since=state.condition_since,
        firing_since=state.firing_since,
        last_value=state.last_value,
        last_notified_at=now,
        window=state.window,
    )
