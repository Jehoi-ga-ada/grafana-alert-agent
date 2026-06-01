"""Tests for YAML rule parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from gaa.config.rule_loader import RuleConfigError, load_rules, parse_rules
from gaa.domain.models import Comparator, Severity

_VALID_DOC = {
    "defaults": {"env": "prod", "cooldown": 600, "for": 0},
    "rules": [
        {
            "name": "app_down",
            "title": "App down",
            "expr": "up",
            "comparator": "eq",
            "threshold": 0,
            "severity": "critical",
            "for": 60,
            "panel_id": 11,
            "correlations": {"logs": {"errs": '{team="g"}'}},
        },
        {
            "name": "high_cpu",
            "title": "CPU",
            "expr": "cpu",
            "comparator": "gt",
            "threshold": 85,
            "severity": "warning",
        },
    ],
}


class TestParseRules:
    def test_parses_valid_document(self):
        rules = parse_rules(_VALID_DOC)
        assert len(rules) == 2
        assert rules[0].comparator == Comparator.EQ
        assert rules[0].for_seconds == 60

    def test_defaults_apply_when_rule_omits_field(self):
        rules = parse_rules(_VALID_DOC)
        assert rules[1].cooldown == 600  # inherited from defaults
        assert rules[1].severity == Severity.WARNING

    def test_rule_value_overrides_default(self):
        rules = parse_rules(_VALID_DOC)
        assert rules[0].for_seconds == 60  # overrides default 0

    def test_rejects_duplicate_names(self):
        doc = {"rules": [_VALID_DOC["rules"][0], _VALID_DOC["rules"][0]]}
        with pytest.raises(RuleConfigError, match="duplicate"):
            parse_rules(doc)

    def test_rejects_missing_rules_list(self):
        with pytest.raises(RuleConfigError, match="non-empty"):
            parse_rules({"defaults": {}})

    def test_rejects_invalid_comparator(self):
        doc = {"rules": [{**_VALID_DOC["rules"][1], "comparator": "approximately"}]}
        with pytest.raises(RuleConfigError, match="invalid rule"):
            parse_rules(doc)


class TestLoadRules:
    def test_loads_shipped_rules_file(self):
        # The real config must always parse.
        path = Path(__file__).parents[2] / "config" / "rules.yaml"
        rules = load_rules(path)
        assert any(r.name == "app_down" for r in rules)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RuleConfigError, match="not found"):
            load_rules(tmp_path / "nope.yaml")
