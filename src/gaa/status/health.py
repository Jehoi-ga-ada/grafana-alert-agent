"""Pure point-in-time health evaluation. No state, no dedup, no incidents."""

from __future__ import annotations

from gaa.config.rule_models import Rule
from gaa.domain.evaluation import _representative
from gaa.domain.models import QueryResult, Severity
from gaa.status.models import SEVERITY_ORDER, HealthReport, RuleHealth, Verdict

_CRIT_SEVERITIES = (Severity.CRITICAL, Severity.HIGH)


def _verdict_for(rule: Rule, breaching: bool) -> Verdict:
    if not breaching:
        return Verdict.OK
    return Verdict.CRIT if rule.severity in _CRIT_SEVERITIES else Verdict.WARN


def evaluate_health(
    rules: tuple[Rule, ...],
    results: dict[str, QueryResult | None],
    now: float,
) -> HealthReport:
    """Map each rule's current query result to a health verdict and roll up."""
    healths: list[RuleHealth] = []
    for rule in rules:
        result = results.get(rule.name)
        if result is None or result.is_empty:
            healths.append(RuleHealth(rule.name, rule.title, Verdict.UNKNOWN, None))
            continue
        breaching, value = _representative(result, rule)
        healths.append(RuleHealth(rule.name, rule.title, _verdict_for(rule, breaching), value))
    return HealthReport(rules=tuple(healths), overall=_rollup(healths), at=now)


def _rollup(healths: list[RuleHealth]) -> Verdict:
    present = [h.verdict for h in healths if h.verdict != Verdict.UNKNOWN]
    if not present:
        return Verdict.UNKNOWN
    return max(present, key=lambda v: SEVERITY_ORDER[v])
