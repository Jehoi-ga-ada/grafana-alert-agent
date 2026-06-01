"""Anomaly sweeper: query current+baseline, detect, edge-trigger + cooldown notify.

`run_once` is testable with fakes + an injected clock; `serve` is the periodic
loop (excluded from the coverage gate, like Daemon.serve).
"""

from __future__ import annotations

import asyncio
import logging

from gaa.anomaly.detection import baseline_query, evaluate_anomaly
from gaa.anomaly.models import AnomalyCheck, AnomalyResult, AnomalyVerdict
from gaa.clients.protocols import MetricsSource, Notifier
from gaa.domain.dedup import _in_cooldown
from gaa.notify.embed import build_anomaly_embed
from gaa.orchestrator.timeutil import iso
from gaa.state.store import StateStore

logger = logging.getLogger(__name__)

_ANOMALOUS = AnomalyVerdict.ANOMALOUS.value
_NORMAL = AnomalyVerdict.NORMAL.value


async def evaluate_all(checks, metrics, now: float) -> list[AnomalyResult]:
    """Evaluate every check without touching state (for on-demand `!anomalies`)."""
    out: list[AnomalyResult] = []
    for check in checks:
        try:
            current = await metrics.query_instant(check.expr)
            baseline = await metrics.query_instant(baseline_query(check))
        except Exception as exc:
            logger.warning("anomaly query failed for %s: %s", check.name, exc)
            continue
        out.append(evaluate_anomaly(check, current, baseline, now))
    return out


class AnomalySweeper:
    def __init__(
        self,
        *,
        checks: tuple[AnomalyCheck, ...],
        metrics: MetricsSource,
        notifier: Notifier,
        store: StateStore,
        clock,
        interval: float = 900.0,
    ) -> None:
        self._checks = checks
        self._metrics = metrics
        self._notifier = notifier
        self._store = store
        self._clock = clock
        self._interval = interval
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run_once(self, now: float) -> list[AnomalyResult]:
        """Evaluate every check; notify on edges. Returns the freshly-notified anomalies."""
        notified: list[AnomalyResult] = []
        for check in self._checks:
            try:
                current = await self._metrics.query_instant(check.expr)
                baseline = await self._metrics.query_instant(baseline_query(check))
            except Exception as exc:
                logger.warning("anomaly query failed for %s: %s", check.name, exc)
                continue
            result = evaluate_anomaly(check, current, baseline, now)
            if await self._handle(check, result, now):
                notified.append(result)
        return notified

    async def _handle(self, check: AnomalyCheck, result: AnomalyResult, now: float) -> bool:
        prev = await self._store.get_anomaly_state(check.name)
        prev_verdict = prev[0] if prev else _NORMAL
        last_notified = prev[1] if prev else None

        if result.verdict == AnomalyVerdict.ANOMALOUS:
            if prev_verdict != _ANOMALOUS and not _in_cooldown(last_notified, check.cooldown, now):
                await self._notifier.send(embed=build_anomaly_embed(result, "alert", iso(now)))
                await self._store.set_anomaly_state(check.name, _ANOMALOUS, now)
                return True
            await self._store.set_anomaly_state(check.name, _ANOMALOUS, last_notified)
            return False

        if result.verdict == AnomalyVerdict.NORMAL:
            if prev_verdict == _ANOMALOUS:
                await self._notifier.send(embed=build_anomaly_embed(result, "recovery", iso(now)))
            await self._store.set_anomaly_state(check.name, _NORMAL, last_notified)
            return False

        return False  # SKIPPED — leave state untouched

    async def serve(self) -> None:  # pragma: no cover - periodic loop
        if not self._checks:
            logger.info("no anomaly checks configured; sweeper idle")
            return
        logger.info("anomaly sweeper: %d checks, %ss interval", len(self._checks), self._interval)
        while not self._stop.is_set():
            try:
                fired = await self.run_once(self._clock())
                if fired:
                    logger.info("anomalies notified: %s", [r.name for r in fired])
            except Exception as exc:
                logger.exception("anomaly sweep error: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass
