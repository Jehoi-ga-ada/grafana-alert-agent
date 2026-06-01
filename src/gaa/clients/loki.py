"""Log queries (LogQL) via the Grafana datasource proxy (Loki)."""

from __future__ import annotations

import logging

from gaa.clients.grafana import GrafanaClient
from gaa.clients.parse import parse_loki
from gaa.domain.models import TimeWindow

logger = logging.getLogger(__name__)

_LOKI_TYPE = "loki"


class LogsClient:
    """Read-only LogQL range queries. Implements LogSource."""

    def __init__(self, grafana: GrafanaClient, ds_uid: str | None = None) -> None:
        self._grafana = grafana
        self._ds_uid = ds_uid

    async def _uid(self) -> str:
        if self._ds_uid is None:
            self._ds_uid = await self._grafana.resolve_datasource_uid(_LOKI_TYPE)
        return self._ds_uid

    async def query_logs(self, logql: str, window: TimeWindow, limit: int = 50) -> tuple[str, ...]:
        try:
            uid = await self._uid()
            payload = await self._grafana.proxy_get(
                uid,
                "loki/api/v1/query_range",
                {
                    "query": logql,
                    "start": int(window.start * 1e9),  # Loki wants nanoseconds
                    "end": int(window.end * 1e9),
                    "limit": limit,
                    "direction": "backward",
                },
            )
            return parse_loki(payload, limit)
        except Exception as exc:  # logs are best-effort enrichment, never fatal
            logger.warning("loki query failed (continuing without logs): %s", exc)
            return ()
