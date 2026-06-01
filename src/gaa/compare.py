"""Compare a metric now vs a historical baseline (pure helpers)."""

from __future__ import annotations

from gaa.anomaly.detection import with_offset
from gaa.domain.models import QueryResult

# Friendly aliases → PromQL. Unknown names are treated as raw PromQL.
METRIC_ALIASES: dict[str, str] = {
    "p99": 'max(http_request_duration_seconds{quantile="0.99"})',
    "p90": 'max(http_request_duration_seconds{quantile="0.9"})',
    "error_rate": 'sum(rate(http_requests_total{status_code=~"5.."}[5m])) '
    "/ clamp_min(sum(rate(http_requests_total[5m])), 0.001) * 100",
    "req_rate": "sum(rate(http_requests_total[5m]))",
    "inflight": "sum(http_requests_in_flight)",
    "memory": 'max(process_resident_memory_bytes{job="url-shortener"})',
    "goroutines": 'max(go_goroutines{job="url-shortener"})',
}


def resolve_metric(name: str) -> str:
    return METRIC_ALIASES.get(name.lower().strip(), name)


def baseline_expr(expr: str, lookback: str) -> str:
    return with_offset(expr, lookback)


def _agg(result: QueryResult) -> float | None:
    if result.is_empty:
        return None
    return max(s.value for s in result.samples)


def compute_comparison(current: QueryResult, baseline: QueryResult) -> dict:
    """Return {current, baseline, delta_pct, arrow} for two query results."""
    cur = _agg(current)
    base = _agg(baseline)
    if cur is None:
        return {"current": None, "baseline": base, "delta_pct": None, "arrow": "—"}
    if base is None or base == 0:
        return {"current": cur, "baseline": base, "delta_pct": None, "arrow": "—"}
    delta_pct = (cur - base) / abs(base) * 100.0
    arrow = "▲" if delta_pct > 0 else ("▼" if delta_pct < 0 else "→")
    return {"current": cur, "baseline": base, "delta_pct": delta_pct, "arrow": arrow}


def format_comparison(label: str, lookback: str, cmp: dict) -> str:
    cur = cmp["current"]
    base = cmp["baseline"]
    if cur is None:
        return f"**{label}**: no current data."
    if cmp["delta_pct"] is None:
        return f"**{label}**: now `{cur:g}` (no baseline {lookback} ago)."
    return (
        f"**{label}** {cmp['arrow']} `{cmp['delta_pct']:+.1f}%`\n"
        f"now `{cur:g}` vs `{base:g}` ({lookback} ago)"
    )
