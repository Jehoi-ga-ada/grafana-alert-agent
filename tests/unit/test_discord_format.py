"""Tests for the pure Discord bot helpers (command parsing + formatting)."""

from __future__ import annotations

from gaa.discord_bot.format import (
    chunk_message,
    format_dashboards,
    format_help,
    format_incidents,
    parse_command,
    parse_shot,
    strip_mentions,
)
from gaa.domain.models import Incident, Severity


class TestParseCommand:
    def test_plain_text_is_chat(self):
        cmd = parse_command("why is latency high?")
        assert cmd.name is None
        assert cmd.text == "why is latency high?"

    def test_strips_mention_then_chat(self):
        cmd = parse_command("<@123456> is the app up?")
        assert cmd.name is None
        assert cmd.text == "is the app up?"

    def test_command_with_args(self):
        cmd = parse_command("!shot 8 30")
        assert cmd.name == "shot"
        assert cmd.args == ["8", "30"]

    def test_ask_command_keeps_text(self):
        cmd = parse_command("!ask what happened to redis?")
        assert cmd.name == "ask"
        assert cmd.text == "what happened to redis?"

    def test_bare_prefix_is_chat(self):
        assert parse_command("!").name is None


def test_strip_mentions():
    assert strip_mentions("<@!42> hi <@99>") == "hi"


class TestParseShot:
    def test_default_dashboard_panel_and_minutes(self):
        req = parse_shot(["8", "30"])
        assert (req.dashboard, req.panel_id, req.minutes) == (None, 8, 30)

    def test_default_minutes(self):
        req = parse_shot(["8"])
        assert (req.dashboard, req.panel_id, req.minutes) == (None, 8, 60)

    def test_dashboard_specified(self):
        req = parse_shot(["adrwn4x", "3", "15"])
        assert (req.dashboard, req.panel_id, req.minutes) == ("adrwn4x", 3, 15)

    def test_dashboard_with_default_minutes(self):
        req = parse_shot(["traces", "9"])
        assert (req.dashboard, req.panel_id, req.minutes) == ("traces", 9, 60)

    def test_dashboard_only_is_whole_dashboard(self):
        req = parse_shot(["mydash"])
        assert req.dashboard == "mydash" and req.panel_id is None

    def test_dashboard_plus_number_is_panel(self):
        # `!shot mydash 30` is panel 30 (numeric 2nd token = panel, not minutes)
        req = parse_shot(["mydash", "30"])
        assert req.dashboard == "mydash" and req.panel_id == 30

    def test_empty(self):
        assert parse_shot([]) is None

    def test_bad_minutes_falls_back(self):
        assert parse_shot(["8", "soon"]).minutes == 60


def test_format_dashboards():
    out = format_dashboards([{"uid": "abc", "title": "Logs", "slug": "logs"}])
    assert "abc" in out and "Logs" in out

def test_format_dashboards_empty():
    assert "No dashboards" in format_dashboards([])


class TestFormatIncidents:
    def test_empty(self):
        assert "All clear" in format_incidents((), now=100.0)

    def test_lists_with_state_and_severity(self):
        incs = (
            Incident(id=1, rule_name="app_down", title="App down", severity=Severity.CRITICAL, fired_at=90.0),
            Incident(
                id=2, rule_name="cpu", title="CPU", severity=Severity.WARNING, fired_at=40.0, resolved_at=80.0
            ),
        )
        out = format_incidents(incs, now=100.0)
        assert "#1" in out and "App down" in out and "firing" in out
        assert "#2" in out and "resolved" in out


class TestChunking:
    def test_short_message_single_chunk(self):
        assert chunk_message("hello") == ["hello"]

    def test_splits_long_message(self):
        text = "\n".join("x" * 100 for _ in range(40))  # ~4000 chars
        chunks = chunk_message(text, limit=2000)
        assert len(chunks) >= 2
        assert all(len(c) <= 2000 for c in chunks)

    def test_splits_single_overlong_line(self):
        chunks = chunk_message("y" * 5000, limit=2000)
        assert all(len(c) <= 2000 for c in chunks)


def test_help_mentions_commands():
    h = format_help()
    assert "!shot" in h and "!incidents" in h
