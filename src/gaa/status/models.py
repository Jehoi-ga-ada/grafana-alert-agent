"""Immutable health-report value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    OK = "ok"
    WARN = "warn"
    CRIT = "crit"
    UNKNOWN = "unknown"


# Ordering for rolling up the worst verdict.
SEVERITY_ORDER: dict[Verdict, int] = {
    Verdict.OK: 0,
    Verdict.UNKNOWN: 1,
    Verdict.WARN: 2,
    Verdict.CRIT: 3,
}


@dataclass(frozen=True, slots=True)
class RuleHealth:
    name: str
    title: str
    verdict: Verdict
    value: float | None


@dataclass(frozen=True, slots=True)
class HealthReport:
    rules: tuple[RuleHealth, ...]
    overall: Verdict
    at: float

    @property
    def is_ok(self) -> bool:
        return self.overall == Verdict.OK
