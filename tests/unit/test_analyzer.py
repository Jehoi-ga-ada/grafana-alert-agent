"""Tests for prompt assembly and the LangChain structured-output analyzer."""

from __future__ import annotations

from gaa.analyzer.claude import LLMAnalyzer
from gaa.analyzer.models import AnalysisSchema
from gaa.analyzer.prompt import build_incident_text, system_blocks
from gaa.domain.models import TimeWindow
from gaa.enrichment.context import ContextBundle, CorrelatedMetric
from tests.conftest import make_rule
from tests.fakes import FakeChatModel


def _bundle(**kw) -> ContextBundle:
    defaults = dict(
        rule=make_rule(title="High error rate", runbook="check the DB"),
        value=12.5,
        window=TimeWindow(1_700_000_000, 1_700_000_300),
        correlated_metrics=(CorrelatedMetric("goroutines", "go_goroutines", ()),),
        logs=("error: pq: connection refused",),
        recent_count=3,
    )
    defaults.update(kw)
    return ContextBundle(**defaults)


class TestPrompt:
    def test_system_block_has_playbook(self):
        blocks = system_blocks()
        assert "url-shortener" in blocks[0]["text"]

    def test_incident_text_includes_specifics(self):
        text = build_incident_text(_bundle())
        assert "High error rate" in text
        assert "12.5" in text
        assert "check the DB" in text
        assert "fired 3 times" in text
        assert "connection refused" in text


class TestLLMAnalyzer:
    async def test_unconfigured_returns_degraded(self):
        result = await LLMAnalyzer(None, configured=False).analyze(_bundle())
        assert result.degraded is True
        assert "High error rate" in result.summary

    async def test_successful_call_maps_schema(self):
        schema = AnalysisSchema(
            summary="DB down",
            likely_cause="Postgres unreachable",
            remediation_steps=["restart postgres", "check creds"],
            severity="critical",
            confidence="high",
        )
        result = await LLMAnalyzer(FakeChatModel(result=schema), configured=True).analyze(_bundle())
        assert result.summary == "DB down"
        assert result.remediation == ("restart postgres", "check creds")
        assert result.degraded is False

    async def test_model_error_returns_degraded(self):
        model = FakeChatModel(error=RuntimeError("bedrock 500"))
        result = await LLMAnalyzer(model, configured=True).analyze(_bundle())
        assert result.degraded is True
        assert "High error rate" in result.summary
