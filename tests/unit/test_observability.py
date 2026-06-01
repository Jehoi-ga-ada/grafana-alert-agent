"""Tests for LangSmith tracing configuration (env-var export, fail-safe)."""

from __future__ import annotations

import os
from types import SimpleNamespace

from gaa.observability import configure_langsmith

_LANGSMITH_VARS = ("LANGSMITH_TRACING", "LANGSMITH_ENDPOINT", "LANGSMITH_API_KEY", "LANGSMITH_PROJECT")


def _settings(**overrides) -> SimpleNamespace:
    base = dict(
        langsmith_tracing=False,
        langsmith_endpoint="https://api.smith.langchain.com",
        langsmith_api_key="",
        langsmith_project="grafana-agent",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _clear_env(monkeypatch) -> None:
    for var in _LANGSMITH_VARS:
        monkeypatch.delenv(var, raising=False)


def test_disabled_when_toggle_off(monkeypatch):
    _clear_env(monkeypatch)
    assert configure_langsmith(_settings(langsmith_tracing=False)) is False
    assert "LANGSMITH_API_KEY" not in os.environ


def test_disabled_when_key_missing(monkeypatch):
    _clear_env(monkeypatch)
    assert configure_langsmith(_settings(langsmith_tracing=True, langsmith_api_key="")) is False
    assert "LANGSMITH_API_KEY" not in os.environ


def test_exports_native_env_vars_when_enabled(monkeypatch):
    _clear_env(monkeypatch)
    enabled = configure_langsmith(
        _settings(langsmith_tracing=True, langsmith_api_key="lsv2_pt_SECRET", langsmith_project="grafana-agent")
    )
    assert enabled is True
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"
    assert os.environ["LANGSMITH_API_KEY"] == "lsv2_pt_SECRET"
    assert os.environ["LANGSMITH_PROJECT"] == "grafana-agent"
