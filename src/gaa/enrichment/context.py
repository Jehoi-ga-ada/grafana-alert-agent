"""Immutable context bundle handed to the analyzer."""

from __future__ import annotations

from dataclasses import dataclass, field

from gaa.config.rule_models import Rule
from gaa.domain.models import Sample, TimeWindow


@dataclass(frozen=True, slots=True)
class CorrelatedMetric:
    label: str
    query: str
    samples: tuple[Sample, ...]

    def summarize(self, limit: int = 8) -> str:
        """Compact human/LLM-readable rendering of the series."""
        if not self.samples:
            return f"{self.label}: (no data)"
        parts = []
        for s in self.samples[:limit]:
            tags = ",".join(f"{k}={v}" for k, v in s.labels if k in ("job", "instance", "status_code", "path", "device"))
            parts.append(f"{tags or '∅'}={s.value:g}")
        return f"{self.label}: " + "; ".join(parts)


@dataclass(frozen=True, slots=True)
class ContextBundle:
    """Everything the analyzer needs to reason about one firing."""

    rule: Rule
    value: float | None
    window: TimeWindow
    correlated_metrics: tuple[CorrelatedMetric, ...] = ()
    logs: tuple[str, ...] = ()
    recent_count: int = 0  # how many times this rule fired recently
