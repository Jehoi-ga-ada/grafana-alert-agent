"""In-memory fakes for the I/O Protocols — used across tests instead of mocks."""

from __future__ import annotations

from gaa.domain.models import QueryResult, Sample, TimeWindow
from gaa.enrichment.context import ContextBundle


class FakeMetrics:
    """MetricsSource backed by a dict of query -> values."""

    def __init__(self, responses: dict[str, list[float]] | None = None) -> None:
        self._responses = responses or {}
        self.queries: list[str] = []

    def set(self, query: str, values: list[float]) -> None:
        self._responses[query] = values

    async def query_instant(self, promql: str) -> QueryResult:
        self.queries.append(promql)
        values = self._responses.get(promql, [])
        samples = tuple(Sample.from_labels({"job": "url-shortener"}, v) for v in values)
        return QueryResult(samples=samples)


class FakeLogs:
    """LogSource returning canned lines."""

    def __init__(self, lines: tuple[str, ...] = ()) -> None:
        self._lines = lines
        self.queries: list[str] = []

    async def query_logs(self, logql: str, window: TimeWindow, limit: int = 50) -> tuple[str, ...]:
        self.queries.append(logql)
        return self._lines[:limit]


class FakeNotifier:
    """Notifier that records what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, embed: dict, image_png: bytes | None = None, image_name: str = "panel.png") -> None:
        self.sent.append({"embed": embed, "image": image_png, "image_name": image_name})


class FakeCapturer:
    """Capturer returning fixed bytes (or None to simulate failure)."""

    def __init__(self, png: bytes | None = b"\x89PNG-fake") -> None:
        self._png = png
        self.calls: list[tuple] = []

    async def capture_panel(
        self, panel_id: int, window: TimeWindow, dashboard_uid=None, dashboard_slug=None
    ) -> bytes | None:
        self.calls.append((panel_id, dashboard_uid))
        return self._png

    async def capture_dashboard(self, window: TimeWindow, dashboard_uid: str, dashboard_slug=None) -> bytes | None:
        self.calls.append(("dashboard", dashboard_uid))
        return self._png


class _FakeStructured:
    def __init__(self, result, error: Exception | None) -> None:
        self._result = result
        self._error = error
        self.calls: list = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self._error is not None:
            raise self._error
        return self._result


class FakeChatModel:
    """Minimal stand-in for a LangChain chat model with structured output."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self._structured = _FakeStructured(result, error)

    def with_structured_output(self, schema):
        return self._structured


class FakeAnalyzer:
    """Analyzer returning a canned analysis."""

    def __init__(self, result) -> None:
        self._result = result
        self.bundles: list[ContextBundle] = []

    async def analyze(self, bundle: ContextBundle):
        self.bundles.append(bundle)
        return self._result
