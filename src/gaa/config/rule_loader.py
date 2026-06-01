"""Load and validate alert rules from YAML into immutable Rule objects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from gaa.config.rule_models import Rule


class RuleConfigError(ValueError):
    """Raised when the rules file is malformed."""


def _merge_defaults(raw_rule: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """Apply file-level defaults under each rule without mutating inputs."""
    merged = dict(defaults)
    merged.update(raw_rule)
    return merged


def parse_rules(document: dict[str, Any]) -> tuple[Rule, ...]:
    """Parse an already-loaded YAML document into validated rules."""
    if not isinstance(document, dict):
        raise RuleConfigError("rules document must be a mapping")

    defaults = document.get("defaults") or {}
    raw_rules = document.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise RuleConfigError("rules document must contain a non-empty 'rules' list")

    rules: list[Rule] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rules):
        if not isinstance(raw, dict):
            raise RuleConfigError(f"rule #{index} is not a mapping")
        merged = _merge_defaults(raw, defaults)
        try:
            rule = Rule.model_validate(merged)
        except Exception as exc:  # pydantic ValidationError -> friendly message
            raise RuleConfigError(f"invalid rule '{raw.get('name', index)}': {exc}") from exc
        if rule.name in seen:
            raise RuleConfigError(f"duplicate rule name '{rule.name}'")
        seen.add(rule.name)
        rules.append(rule)

    return tuple(rules)


def load_rules(path: str | Path) -> tuple[Rule, ...]:
    """Read a YAML rules file and return validated, immutable rules."""
    file_path = Path(path)
    if not file_path.is_file():
        raise RuleConfigError(f"rules file not found: {file_path}")
    try:
        document = yaml.safe_load(file_path.read_text())
    except yaml.YAMLError as exc:
        raise RuleConfigError(f"could not parse YAML: {exc}") from exc
    return parse_rules(document)
