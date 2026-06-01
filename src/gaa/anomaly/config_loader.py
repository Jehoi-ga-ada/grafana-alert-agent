"""Load anomaly checks from YAML (mirrors config/rule_loader.py)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from gaa.anomaly.models import AnomalyCheck


class AnomalyConfigError(ValueError):
    pass


def parse_checks(document: dict[str, Any]) -> tuple[AnomalyCheck, ...]:
    if not isinstance(document, dict):
        raise AnomalyConfigError("anomalies document must be a mapping")
    defaults = document.get("defaults") or {}
    raw = document.get("checks")
    if not isinstance(raw, list) or not raw:
        raise AnomalyConfigError("anomalies document must contain a non-empty 'checks' list")

    checks: list[AnomalyCheck] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise AnomalyConfigError(f"check #{index} is not a mapping")
        merged = {**defaults, **item}
        try:
            check = AnomalyCheck.model_validate(merged)
        except Exception as exc:
            raise AnomalyConfigError(f"invalid check '{item.get('name', index)}': {exc}") from exc
        if check.name in seen:
            raise AnomalyConfigError(f"duplicate check name '{check.name}'")
        seen.add(check.name)
        checks.append(check)
    return tuple(checks)


def load_anomaly_checks(path: str | Path) -> tuple[AnomalyCheck, ...]:
    file_path = Path(path)
    if not file_path.is_file():
        return ()  # anomalies are optional
    try:
        document = yaml.safe_load(file_path.read_text())
    except yaml.YAMLError as exc:
        raise AnomalyConfigError(f"could not parse YAML: {exc}") from exc
    return parse_checks(document)
