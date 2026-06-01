"""Structural interfaces for the I/O adapters — the DI seams used by tests."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gaa.domain.models import QueryResult, TimeWindow


@runtime_checkable
class MetricsSource(Protocol):
    async def query_instant(self, promql: str) -> QueryResult: ...


@runtime_checkable
class LogSource(Protocol):
    async def query_logs(self, logql: str, window: TimeWindow, limit: int = 50) -> tuple[str, ...]: ...


@runtime_checkable
class Notifier(Protocol):
    async def send(
        self,
        *,
        embed: dict,
        image_png: bytes | None = None,
        image_name: str = "panel.png",
    ) -> None: ...


@runtime_checkable
class Capturer(Protocol):
    async def capture_panel(
        self,
        panel_id: int,
        window: TimeWindow,
        dashboard_uid: str | None = None,
        dashboard_slug: str | None = None,
    ) -> bytes | None: ...

    async def capture_dashboard(
        self,
        window: TimeWindow,
        dashboard_uid: str,
        dashboard_slug: str | None = None,
    ) -> bytes | None: ...
