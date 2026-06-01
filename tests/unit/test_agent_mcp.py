"""Tests for the MCP read-only allowlist and launch config."""

from __future__ import annotations

from gaa.agent.mcp import filter_tools, is_allowed, server_config
from gaa.config.settings import Settings


class _Tool:
    def __init__(self, name: str) -> None:
        self.name = name


class TestIsAllowed:
    def test_allows_known_read_tools(self):
        assert is_allowed("query_prometheus")
        assert is_allowed("query_loki_logs")
        assert is_allowed("list_datasources")
        assert is_allowed("get_dashboard_by_uid")

    def test_allows_sift_read_and_analysis_when_enabled(self):
        assert is_allowed("list_sift_investigations")
        assert is_allowed("get_sift_analysis")
        assert is_allowed("find_slow_requests", allow_sift=True)
        assert is_allowed("find_error_pattern_logs", allow_sift=True)

    def test_blocks_sift_analysis_when_disabled(self):
        assert is_allowed("find_slow_requests", allow_sift=False) is False

    def test_blocks_mutating_tools(self):
        for name in ("create_dashboard", "update_dashboard", "delete_alert_rule",
                     "add_silence", "write_thing", "save_dashboard", "move_dashboard"):
            assert is_allowed(name) is False

    def test_blocks_unknown_tools_fail_closed(self):
        assert is_allowed("some_random_tool") is False
        assert is_allowed("navigate_to_explore") is False


class TestFilterTools:
    def test_keeps_only_allowlisted(self):
        tools = [
            _Tool("query_prometheus"),
            _Tool("find_slow_requests"),
            _Tool("create_dashboard"),
            _Tool("delete_alert_rule"),
            _Tool("update_dashboard"),
            _Tool("navigate_to_explore"),
        ]
        kept = {t.name for t in filter_tools(tools, allow_sift=True)}
        assert kept == {"query_prometheus", "find_slow_requests"}

    def test_sift_dropped_when_disabled(self):
        tools = [_Tool("query_prometheus"), _Tool("find_slow_requests")]
        kept = {t.name for t in filter_tools(tools, allow_sift=False)}
        assert kept == {"query_prometheus"}


class TestServerConfig:
    def _settings(self, **kw) -> Settings:
        base = dict(grafana_url="https://g.test", grafana_sa_token="tok", grafana_ca_cert="", tls_insecure=False)
        base.update(kw)
        return Settings(_env_file=None, **base)

    def test_disable_write_when_sift_off(self):
        cfg = server_config(self._settings(allow_sift=False))
        assert "-disable-write" in cfg["args"]
        assert cfg["transport"] == "stdio"

    def test_no_disable_write_when_sift_on(self):
        # Sift analysis needs write; the fail-closed allowlist is the read-only gate.
        cfg = server_config(self._settings(allow_sift=True))
        assert "-disable-write" not in cfg["args"]

    def test_enabled_tools_whitelist(self):
        cfg = server_config(self._settings())
        idx = cfg["args"].index("-enabled-tools")
        cats = cfg["args"][idx + 1]
        assert "prometheus" in cats and "loki" in cats and "sift" in cats
        assert "admin" not in cats and "api" not in cats and "oncall" not in cats

    def test_token_passed_in_env(self):
        cfg = server_config(self._settings())
        assert cfg["env"]["GRAFANA_SERVICE_ACCOUNT_TOKEN"] == "tok"
        assert cfg["env"]["GRAFANA_API_KEY"] == "tok"
        assert cfg["env"]["GRAFANA_URL"] == "https://g.test"

    def test_insecure_adds_skip_verify(self):
        cfg = server_config(self._settings(tls_insecure=True))
        assert "-tls-skip-verify" in cfg["args"]

    def test_ca_file_when_secure(self, tmp_path):
        ca = tmp_path / "ca.crt"
        cfg = server_config(self._settings(grafana_ca_cert=str(ca)))
        assert "-tls-ca-file" in cfg["args"]
