"""Validated, immutable alert-rule models (schema-based boundary validation)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from gaa.domain.models import Comparator, Severity


class Correlations(BaseModel):
    """Extra signals Claude should see to find the root cause, not the symptom."""

    model_config = ConfigDict(frozen=True)

    metrics: dict[str, str] = Field(default_factory=dict)  # label -> PromQL
    logs: dict[str, str] = Field(default_factory=dict)  # label -> LogQL


class Rule(BaseModel):
    """A single alert rule. Frozen — treat as immutable."""

    model_config = ConfigDict(frozen=True)

    name: str
    title: str
    expr: str
    comparator: Comparator
    threshold: float
    severity: Severity
    job: str = "url-shortener"
    env: str = "prod"
    for_: int = Field(default=0, alias="for", ge=0)  # seconds the condition must hold
    cooldown: int = Field(default=900, ge=0)  # seconds before re-notifying
    panel_id: int | None = None
    runbook: str = ""
    correlations: Correlations = Field(default_factory=Correlations)

    @property
    def for_seconds(self) -> int:
        return self.for_
