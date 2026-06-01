"""Immutable domain value objects shared across the agent.

These are pure data carriers with no I/O. Everything is frozen — "mutating"
means constructing a new instance (see the coding-style immutability rule).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    WARNING = "warning"
    INFO = "info"


class Comparator(StrEnum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    EQ = "eq"
    NE = "ne"


class AlertStatus(StrEnum):
    INACTIVE = "inactive"  # condition false; nothing firing
    PENDING = "pending"  # condition true but for-duration not yet satisfied
    FIRING = "firing"  # condition held for >= for-duration
    RESOLVED = "resolved"  # transitioned out of firing (transient, for notification)


# Discord embed colours per severity (decimal RGB).
SEVERITY_COLORS: dict[Severity, int] = {
    Severity.CRITICAL: 0xE01E5A,  # red
    Severity.HIGH: 0xED8F1C,  # orange
    Severity.WARNING: 0xECB22E,  # amber
    Severity.INFO: 0x2EB67D,  # green
}
RESOLVED_COLOR = 0x2EB67D


@dataclass(frozen=True, slots=True)
class Sample:
    """A single PromQL result series: its labels and scalar value."""

    labels: tuple[tuple[str, str], ...]
    value: float

    @property
    def labels_dict(self) -> dict[str, str]:
        return dict(self.labels)

    @classmethod
    def from_labels(cls, labels: dict[str, str], value: float) -> Sample:
        return cls(labels=tuple(sorted(labels.items())), value=value)


@dataclass(frozen=True, slots=True)
class QueryResult:
    """The result of one instant PromQL query."""

    samples: tuple[Sample, ...]

    @property
    def is_empty(self) -> bool:
        return len(self.samples) == 0


@dataclass(frozen=True, slots=True)
class TimeWindow:
    """An inclusive time window in epoch seconds — drives screenshot ranges."""

    start: float
    end: float

    @property
    def start_ms(self) -> int:
        return int(self.start * 1000)

    @property
    def end_ms(self) -> int:
        return int(self.end * 1000)


@dataclass(frozen=True, slots=True)
class RuleState:
    """Per-rule evaluation state — the single source of truth for transitions."""

    name: str
    status: AlertStatus = AlertStatus.INACTIVE
    condition_since: float | None = None  # when the condition first became true
    firing_since: float | None = None  # when it crossed into FIRING
    last_value: float | None = None
    last_notified_at: float | None = None
    window: TimeWindow | None = None

    @classmethod
    def initial(cls, name: str) -> RuleState:
        return cls(name=name)


@dataclass(frozen=True, slots=True)
class Incident:
    """A persisted alert occurrence with its AI analysis (history record)."""

    rule_name: str
    title: str
    severity: Severity
    fired_at: float
    value: float | None = None
    summary: str = ""
    likely_cause: str = ""
    remediation: tuple[str, ...] = ()
    confidence: str = ""
    dashboard_url: str = ""
    has_screenshot: bool = False
    resolved_at: float | None = None
    thread_id: str = ""  # Discord thread for this incident (per-incident threads)
    id: int | None = None

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None
