"""Pure anomaly detection: compare current value to a baseline. No I/O."""

from __future__ import annotations

import re

from gaa.anomaly.models import AnomalyCheck, AnomalyResult, AnomalyVerdict, Direction
from gaa.domain.models import QueryResult

_LOOKBACK_RE = re.compile(r"^\d+[smhdw]$")


class AnomalyConfigError(ValueError):
    pass


def with_offset(expr: str, lookback: str) -> str:
    """Wrap a PromQL expression to read the baseline ``lookback`` ago.

    Conservative: only valid Prometheus duration strings are accepted; anything
    else should use an explicit ``baseline_expr``.
    """
    if not _LOOKBACK_RE.match(lookback):
        raise AnomalyConfigError(f"invalid lookback '{lookback}' (use e.g. 1h, 1d, 7d)")
    return f"({expr}) offset {lookback}"


def baseline_query(check: AnomalyCheck) -> str:
    return check.baseline_expr or with_offset(check.expr, check.lookback)


def _agg(result: QueryResult) -> float | None:
    if result.is_empty:
        return None
    return max(s.value for s in result.samples)


def evaluate_anomaly(
    check: AnomalyCheck,
    current: QueryResult,
    baseline: QueryResult,
    now: float,
) -> AnomalyResult:
    cur = _agg(current)
    base = _agg(baseline)
    if cur is None or base is None or abs(base) < check.min_baseline:
        return AnomalyResult(check.name, check.title, AnomalyVerdict.SKIPPED, cur, base, None, now,
                             "no data or baseline too small")

    ratio = cur / base
    deviated = _deviates(ratio, check.factor, check.direction)
    verdict = AnomalyVerdict.ANOMALOUS if deviated else AnomalyVerdict.NORMAL
    reason = f"{ratio:.2f}× baseline ({cur:g} vs {base:g})" if deviated else ""
    return AnomalyResult(check.name, check.title, verdict, cur, base, ratio, now, reason)


def _deviates(ratio: float, factor: float, direction: Direction) -> bool:
    if direction == Direction.ABOVE:
        return ratio > factor
    if direction == Direction.BELOW:
        return ratio < 1.0 / factor
    return ratio > factor or ratio < 1.0 / factor
