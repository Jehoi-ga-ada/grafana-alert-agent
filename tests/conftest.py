"""Shared test fixtures and builders."""

from __future__ import annotations

import pytest

from gaa.config.rule_models import Rule
from gaa.domain.models import Comparator, QueryResult, Sample, Severity


def make_rule(**overrides) -> Rule:
    """Build a Rule with sensible defaults, overridable per test."""
    data = {
        "name": "test_rule",
        "title": "Test Rule",
        "expr": "up",
        "comparator": Comparator.GT,
        "threshold": 5.0,
        "severity": Severity.HIGH,
        "for": 0,
        "cooldown": 900,
    }
    data.update(overrides)
    return Rule.model_validate(data)


def make_result(*values: float, labels: dict[str, str] | None = None) -> QueryResult:
    """Build a QueryResult from one or more scalar values."""
    base = labels or {"job": "url-shortener"}
    samples = tuple(Sample.from_labels({**base, "i": str(idx)}, v) for idx, v in enumerate(values))
    return QueryResult(samples=samples)


def empty_result() -> QueryResult:
    return QueryResult(samples=())


@pytest.fixture
def rule() -> Rule:
    return make_rule()
