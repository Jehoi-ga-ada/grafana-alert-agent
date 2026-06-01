"""Alert root-cause analyzer (structured single call via LangChain).

Uses the same chat model as the bot, with structured output. Pre-enriched
ContextBundle in, AnalysisResult out. Degrades gracefully so analysis failure
never blocks the Discord alert. No MCP — keeps the daemon LLM-light.
"""

from __future__ import annotations

import logging

from gaa.analyzer.models import AnalysisResult, AnalysisSchema
from gaa.analyzer.playbook import system_prefix
from gaa.analyzer.prompt import build_incident_text
from gaa.enrichment.context import ContextBundle

logger = logging.getLogger(__name__)


class LLMAnalyzer:
    """Implements Analyzer using a LangChain chat model with structured output."""

    def __init__(self, model, configured: bool) -> None:
        self._model = model
        self._configured = configured

    async def analyze(self, bundle: ContextBundle) -> AnalysisResult:
        fallback_summary = (
            f"{bundle.rule.title}: observed value {bundle.value:g}"
            if bundle.value is not None
            else bundle.rule.title
        )
        if not self._configured or self._model is None:
            logger.warning("no LLM credentials; using degraded analysis")
            return AnalysisResult.fallback(fallback_summary)
        try:
            structured = self._model.with_structured_output(AnalysisSchema)
            result: AnalysisSchema = await structured.ainvoke(
                [
                    ("system", system_prefix()),
                    ("user", build_incident_text(bundle)),
                ]
            )
            return _to_result(result, fallback_summary)
        except Exception as exc:  # API/network failure must not block the alert
            logger.error("LLM analysis failed: %s", exc)
            return AnalysisResult.fallback(fallback_summary)


def _to_result(schema: AnalysisSchema, fallback_summary: str) -> AnalysisResult:
    return AnalysisResult(
        summary=schema.summary or fallback_summary,
        likely_cause=schema.likely_cause,
        remediation=tuple(schema.remediation_steps),
        severity=schema.severity,
        confidence=schema.confidence,
    )
