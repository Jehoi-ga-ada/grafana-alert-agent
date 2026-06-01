"""Tests for settings, TLS config, and the null capturer."""

from __future__ import annotations

import pytest

from gaa.clients.tls import build_ssl_context, build_verify
from gaa.config.settings import Settings
from gaa.domain.models import TimeWindow
from gaa.screenshot.capture import NullCapturer


class TestBuildVerify:
    def test_insecure_returns_false(self):
        assert build_verify(None, insecure=True) is False

    def test_ca_path_returned_as_string(self, tmp_path):
        ca = tmp_path / "ca.crt"
        ca.write_text("x")
        assert build_verify(ca, insecure=False) == str(ca)

    def test_missing_ca_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_verify(tmp_path / "absent.crt", insecure=False)

    def test_no_ca_defaults_to_true(self):
        assert build_verify(None, insecure=False) is True


class TestBuildSslContext:
    def test_insecure_context_disables_verification(self):
        ctx = build_ssl_context(None, insecure=True)
        assert ctx.check_hostname is False

    def test_missing_ca_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            build_ssl_context(tmp_path / "nope.crt", insecure=False)


class TestSettings:
    def _settings(self, **kw) -> Settings:
        base = dict(grafana_url="https://g.test/", grafana_ca_cert="", tls_insecure=False)
        base.update(kw)
        return Settings(_env_file=None, **base)

    def test_strips_trailing_slash(self):
        assert self._settings().grafana_url == "https://g.test"

    def test_verify_true_without_ca(self):
        assert self._settings().verify is True

    def test_verify_false_when_insecure(self):
        assert self._settings(tls_insecure=True).verify is False

    def test_verify_uses_ca_path(self, tmp_path):
        assert self._settings(grafana_ca_cert=str(tmp_path / "ca.crt")).verify.endswith("ca.crt")

    def test_require_raises_on_missing(self):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            self._settings(anthropic_api_key="").require("anthropic_api_key")

    def test_require_passes_when_present(self):
        self._settings(anthropic_api_key="sk").require("anthropic_api_key")  # no raise


class TestNullCapturer:
    async def test_returns_none(self):
        assert await NullCapturer().capture_panel(1, TimeWindow(0, 1)) is None
