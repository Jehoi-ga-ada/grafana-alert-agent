"""Anomaly check config + result value objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Direction(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    BOTH = "both"


class AnomalyVerdict(StrEnum):
    NORMAL = "normal"
    ANOMALOUS = "anomalous"
    SKIPPED = "skipped"  # no data / baseline too small


class AnomalyCheck(BaseModel):
    """A single anomaly check. Frozen — treat as immutable."""

    model_config = ConfigDict(frozen=True)

    name: str
    title: str
    expr: str
    baseline_expr: str | None = None  # explicit baseline; else expr + offset
    lookback: str = "1d"  # PromQL offset for the baseline
    factor: float = Field(default=2.0, gt=1.0)  # deviation multiple to flag
    direction: Direction = Direction.BOTH
    min_baseline: float = 0.01  # ignore near-zero baselines (avoid noise)
    cooldown: int = Field(default=3600, ge=0)


@dataclass(frozen=True, slots=True)
class AnomalyResult:
    name: str
    title: str
    verdict: AnomalyVerdict
    current: float | None
    baseline: float | None
    ratio: float | None
    at: float
    reason: str = ""

    @property
    def is_anomalous(self) -> bool:
        return self.verdict == AnomalyVerdict.ANOMALOUS
