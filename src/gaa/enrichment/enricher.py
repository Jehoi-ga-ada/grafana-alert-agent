"""Gather correlated metrics + logs concurrently for a firing rule."""

from __future__ import annotations

import asyncio
import logging

from gaa.clients.protocols import LogSource, MetricsSource
from gaa.config.rule_models import Rule
from gaa.domain.models import TimeWindow
from gaa.enrichment.context import ContextBundle, CorrelatedMetric

logger = logging.getLogger(__name__)

_MAX_LOG_LINES = 40


class Enricher:
    def __init__(self, metrics: MetricsSource, logs: LogSource) -> None:
        self._metrics = metrics
        self._logs = logs

    async def enrich(
        self,
        rule: Rule,
        value: float | None,
        window: TimeWindow,
        recent_count: int = 0,
    ) -> ContextBundle:
        metrics_task = self._gather_metrics(rule)
        logs_task = self._gather_logs(rule, window)
        correlated, logs = await asyncio.gather(metrics_task, logs_task)
        return ContextBundle(
            rule=rule,
            value=value,
            window=window,
            correlated_metrics=correlated,
            logs=logs,
            recent_count=recent_count,
        )

    async def _gather_metrics(self, rule: Rule) -> tuple[CorrelatedMetric, ...]:
        items = list(rule.correlations.metrics.items())
        if not items:
            return ()

        async def run(label: str, query: str) -> CorrelatedMetric:
            try:
                result = await self._metrics.query_instant(query)
                return CorrelatedMetric(label=label, query=query, samples=result.samples)
            except Exception as exc:  # correlation is best-effort
                logger.warning("correlated metric '%s' failed: %s", label, exc)
                return CorrelatedMetric(label=label, query=query, samples=())

        return tuple(await asyncio.gather(*(run(lbl, q) for lbl, q in items)))

    async def _gather_logs(self, rule: Rule, window: TimeWindow) -> tuple[str, ...]:
        lines: list[str] = []
        for label, logql in rule.correlations.logs.items():
            fetched = await self._logs.query_logs(logql, window, limit=_MAX_LOG_LINES)
            lines.extend(fetched)
            if len(lines) >= _MAX_LOG_LINES:
                break
        return tuple(lines[:_MAX_LOG_LINES])
