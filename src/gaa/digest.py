"""Scheduled daily digest — posts health + recent incidents + anomalies."""

from __future__ import annotations

import asyncio
import logging

from gaa.anomaly.sweep import evaluate_all
from gaa.notify.embed import build_digest_embed
from gaa.orchestrator.timeutil import SECONDS_PER_DAY, iso
from gaa.status.service import gather_health

logger = logging.getLogger(__name__)


class DigestService:
    def __init__(self, *, core, notifier, clock, interval: float) -> None:
        self._core = core
        self._notifier = notifier
        self._clock = clock
        self._interval = interval
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def post_digest(self, now: float) -> None:
        report = await gather_health(self._core.metrics, self._core.rules, now)
        incidents = await self._core.store.list_incidents(50)
        recent = [i for i in incidents if i.fired_at >= now - SECONDS_PER_DAY]
        anomalies = [
            r for r in await evaluate_all(self._core.anomaly_checks, self._core.metrics, now) if r.is_anomalous
        ]
        await self._notifier.send(embed=build_digest_embed(report, recent, anomalies, iso(now)))

    async def serve(self) -> None:  # pragma: no cover - periodic loop
        if self._interval <= 0:
            logger.info("daily digest disabled")
            return
        logger.info("daily digest every %ss", self._interval)
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                try:
                    await self.post_digest(self._clock())
                except Exception as exc:
                    logger.exception("digest error: %s", exc)
