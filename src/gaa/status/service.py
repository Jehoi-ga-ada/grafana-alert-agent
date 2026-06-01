"""Thin async orchestration: gather current values, then evaluate (pure)."""

from __future__ import annotations

import asyncio
import logging

from gaa.clients.protocols import MetricsSource
from gaa.config.rule_models import Rule
from gaa.domain.models import QueryResult
from gaa.status.health import evaluate_health
from gaa.status.models import HealthReport

logger = logging.getLogger(__name__)


async def gather_health(
    metrics: MetricsSource, rules: tuple[Rule, ...], now: float
) -> HealthReport:
    async def query(rule: Rule) -> tuple[str, QueryResult | None]:
        try:
            return rule.name, await metrics.query_instant(rule.expr)
        except Exception as exc:
            logger.warning("status query failed for %s: %s", rule.name, exc)
            return rule.name, None

    pairs = await asyncio.gather(*(query(r) for r in rules))
    return evaluate_health(rules, dict(pairs), now)
