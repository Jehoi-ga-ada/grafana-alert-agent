"""Metrics queries via the Grafana datasource proxy (VictoriaMetrics/Prometheus)."""

from __future__ import annotations

import logging

from gaa.clients.grafana import GrafanaClient
from gaa.clients.parse import parse_instant
from gaa.domain.models import QueryResult

logger = logging.getLogger(__name__)

_PROM_TYPE = "prometheus"


class MetricsClient:
    """Read-only instant PromQL queries. Implements MetricsSource."""

    def __init__(self, grafana: GrafanaClient, ds_uid: str | None = None) -> None:
        self._grafana = grafana
        self._ds_uid = ds_uid

    async def _uid(self) -> str:
        if self._ds_uid is None:
            self._ds_uid = await self._grafana.resolve_datasource_uid(_PROM_TYPE)
        return self._ds_uid

    async def query_instant(self, promql: str) -> QueryResult:
        uid = await self._uid()
        payload = await self._grafana.proxy_get(uid, "api/v1/query", {"query": promql})
        return parse_instant(payload)
