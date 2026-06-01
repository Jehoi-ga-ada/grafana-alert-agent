"""Pure parsers for Prometheus / Loki HTTP API responses."""

from __future__ import annotations

from typing import Any

from gaa.domain.models import QueryResult, Sample


class QueryParseError(ValueError):
    """Raised when a metrics/logs response is not the expected shape."""


def parse_instant(payload: dict[str, Any]) -> QueryResult:
    """Parse a Prometheus instant-query response into a QueryResult.

    Handles both ``vector`` and ``scalar`` result types. Non-finite / unparsable
    values are skipped rather than crashing the poll loop.
    """
    if payload.get("status") != "success":
        raise QueryParseError(f"query failed: {payload.get('error', payload.get('status'))}")

    data = payload.get("data", {})
    result_type = data.get("resultType")
    raw = data.get("result", [])

    if result_type == "scalar":
        value = _to_float(raw[1]) if isinstance(raw, list) and len(raw) == 2 else None
        return QueryResult(samples=() if value is None else (Sample.from_labels({}, value),))

    samples: list[Sample] = []
    for series in raw:
        metric = series.get("metric", {})
        pair = series.get("value")
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        value = _to_float(pair[1])
        if value is None:
            continue
        samples.append(Sample.from_labels(metric, value))
    return QueryResult(samples=tuple(samples))


def parse_loki(payload: dict[str, Any], limit: int = 50) -> tuple[str, ...]:
    """Parse a Loki query_range response into newest-first log lines."""
    if payload.get("status") != "success":
        return ()
    data = payload.get("data", {})
    entries: list[tuple[int, str]] = []
    for stream in data.get("result", []):
        for ts, line in stream.get("values", []):
            try:
                entries.append((int(ts), line))
            except (TypeError, ValueError):
                continue
    entries.sort(key=lambda e: e[0], reverse=True)
    return tuple(line for _, line in entries[:limit])


def _to_float(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return value
