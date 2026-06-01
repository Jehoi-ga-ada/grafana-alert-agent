"""The supervising poll loop.

Each tick: query every rule's PromQL, evaluate (pure), then dispatch firing /
resolved notifications concurrently (bounded). Ticks never overlap, so a rule
cannot be double-fired. A metrics failure skips the tick's transitions rather
than mass-resolving alerts (FR1).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from gaa.clients.protocols import MetricsSource
from gaa.config.rule_models import Rule
from gaa.domain.dedup import NotificationKind, decide_notification, mark_notified
from gaa.domain.evaluation import evaluate_rule
from gaa.domain.models import AlertStatus, RuleState
from gaa.orchestrator.pipeline import AlertPipeline
from gaa.state.store import StateStore

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
HealthCheck = Callable[[], Awaitable[bool]]


class TickReport:
    """Lightweight per-tick summary (handy for tests and logging)."""

    def __init__(self) -> None:
        self.fired: list[str] = []
        self.resolved: list[str] = []
        self.errors: list[str] = []
        self.evaluated = 0


class Daemon:
    def __init__(
        self,
        *,
        rules: tuple[Rule, ...],
        metrics: MetricsSource,
        store: StateStore,
        pipeline: AlertPipeline,
        clock: Clock,
        poll_interval: float = 30.0,
        max_concurrent_pipelines: int = 3,
        health_check: HealthCheck | None = None,
    ) -> None:
        self._rules = rules
        self._metrics = metrics
        self._store = store
        self._pipeline = pipeline
        self._clock = clock
        self._poll_interval = poll_interval
        self._semaphore = asyncio.Semaphore(max_concurrent_pipelines)
        self._health_check = health_check
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def serve(self) -> None:  # pragma: no cover - exercised via run_once in tests
        logger.info("daemon starting: %d rules, %ss interval", len(self._rules), self._poll_interval)
        while not self._stop.is_set():
            try:
                if await self._ready():
                    report = await self.run_once(self._clock())
                    if report.fired or report.resolved or report.errors:
                        logger.info(
                            "tick: fired=%s resolved=%s errors=%s",
                            report.fired, report.resolved, report.errors,
                        )
                else:
                    logger.warning("VPN/Grafana not reachable; skipping tick")
            except Exception as exc:
                logger.exception("unexpected error in tick: %s", exc)
            await self._sleep()
        logger.info("daemon stopped")

    async def _ready(self) -> bool:
        if self._health_check is None:
            return True
        try:
            return await self._health_check()
        except Exception:
            return False

    async def _sleep(self) -> None:  # pragma: no cover
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=self._poll_interval)
        except asyncio.TimeoutError:
            pass

    async def run_once(self, now: float) -> TickReport:
        """Evaluate all rules and dispatch notifications. Pure-ish + side effects."""
        report = TickReport()
        transitions = []

        for rule in self._rules:
            try:
                result = await self._metrics.query_instant(rule.expr)
            except Exception as exc:
                logger.warning("query failed for %s (skipping): %s", rule.name, exc)
                report.errors.append(rule.name)
                continue
            report.evaluated += 1
            prev = await self._store.get_state(rule.name) or RuleState.initial(rule.name)
            new = evaluate_rule(rule, result, prev, now)
            decision = decide_notification(prev, new, rule, now)
            transitions.append((rule, prev, new, decision))

        async with asyncio.TaskGroup() as tg:
            for rule, prev, new, decision in transitions:
                if decision.kind == NotificationKind.FIRING:
                    report.fired.append(rule.name)
                    tg.create_task(self._fire(rule, new, now))
                elif decision.kind == NotificationKind.RESOLVED:
                    report.resolved.append(rule.name)
                    tg.create_task(self._resolve(rule, prev, new, now))
                else:
                    await self._store.put_state(new)

        return report

    async def _fire(self, rule: Rule, new: RuleState, now: float) -> None:
        async with self._semaphore:
            try:
                await self._pipeline.handle_firing(rule, new, now)
            except Exception as exc:
                logger.exception("pipeline failed for %s: %s", rule.name, exc)
            await self._store.put_state(mark_notified(new, now))

    async def _resolve(self, rule: Rule, prev: RuleState, new: RuleState, now: float) -> None:
        try:
            await self._pipeline.handle_resolved(rule, prev, now)
        except Exception as exc:
            logger.exception("resolve pipeline failed for %s: %s", rule.name, exc)
        # After notifying resolution, the rule returns to INACTIVE for next cycle.
        await self._store.put_state(
            RuleState(name=rule.name, status=AlertStatus.INACTIVE, last_value=new.last_value,
                      last_notified_at=new.last_notified_at)
        )
