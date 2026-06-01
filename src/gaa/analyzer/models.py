"""Analyzer interface and result type."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from gaa.enrichment.context import ContextBundle


class AnalysisSchema(BaseModel):
    """Structured-output schema the LLM fills in (LangChain with_structured_output)."""

    summary: str = Field(description="One or two sentences: what is happening and how bad.")
    likely_cause: str = Field(description="The single most likely root cause, with reasoning.")
    remediation_steps: list[str] = Field(
        default_factory=list, description="Ordered, specific commands/steps; most useful first."
    )
    severity: str = Field(description="critical | high | warning | info")
    confidence: str = Field(description="high | medium | low")


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Claude's structured assessment of an alert."""

    summary: str
    likely_cause: str
    remediation: tuple[str, ...]
    severity: str
    confidence: str
    degraded: bool = False  # True when produced by the fallback (no AI)

    @classmethod
    def fallback(cls, summary: str) -> "AnalysisResult":
        return cls(
            summary=summary,
            likely_cause="AI analysis unavailable — see metrics/logs below.",
            remediation=(),
            severity="",
            confidence="low",
            degraded=True,
        )


@runtime_checkable
class Analyzer(Protocol):
    async def analyze(self, bundle: ContextBundle) -> AnalysisResult: ...
