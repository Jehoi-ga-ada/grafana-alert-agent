"""Pure helpers for the Discord bot: command parsing + message formatting."""

from __future__ import annotations

import re
from dataclasses import dataclass

from gaa.domain.models import Incident
from gaa.orchestrator.timeutil import iso  # noqa: F401  (kept for parity / future use)

PREFIX = "!"
DISCORD_LIMIT = 2000

_MENTION_RE = re.compile(r"<@!?\d+>")
_SEV_EMOJI = {"critical": "🔴", "high": "🟠", "warning": "🟡", "info": "🟢"}


@dataclass(frozen=True, slots=True)
class Command:
    name: str | None  # None when it's a free-form chat message
    args: list[str]
    text: str  # full text minus the command token (the chat query)


def strip_mentions(content: str) -> str:
    return _MENTION_RE.sub("", content).strip()


def parse_command(content: str) -> Command:
    """Parse a (mention-stripped) message into a command or a chat query."""
    text = strip_mentions(content)
    if text.startswith(PREFIX):
        parts = text[len(PREFIX):].split()
        if parts:
            name = parts[0].lower()
            args = parts[1:]
            rest = text[len(PREFIX) + len(parts[0]):].strip()
            return Command(name=name, args=args, text=rest)
    return Command(name=None, args=[], text=text)


def _rel(now: float, ts: float) -> str:
    d = int(now - ts)
    if d < 60:
        return f"{d}s ago"
    if d < 3600:
        return f"{d // 60}m ago"
    if d < 86400:
        return f"{d // 3600}h ago"
    return f"{d // 86400}d ago"


def format_incidents(incidents: tuple[Incident, ...], now: float) -> str:
    if not incidents:
        return "No incidents recorded. ✅ All clear."
    lines = ["**Recent incidents**"]
    for inc in incidents:
        emoji = _SEV_EMOJI.get(inc.severity.value, "⚠️")
        state = "🔥 firing" if inc.is_open else "✓ resolved"
        lines.append(f"`#{inc.id}` {emoji} **{inc.title}** — {state} · {_rel(now, inc.fired_at)}")
    return "\n".join(lines)


def format_help() -> str:
    return (
        "**Grafana Alert Agent** (read-only)\n"
        "Just @mention me or DM me a question — I'll query live metrics, logs & incidents.\n\n"
        "Commands:\n"
        f"`{PREFIX}status` — current health verdict (🟢/🟡/🔴) across all rules\n"
        f"`{PREFIX}anomalies` — check for metric anomalies vs baseline\n"
        f"`{PREFIX}compare <metric>` — value now vs yesterday (p99, error_rate, req_rate…)\n"
        f"`{PREFIX}report [incident_id]` — full incident report (RCA + screenshots + .md)\n"
        f"`{PREFIX}ask <question>` — ask the agent (same as mentioning me)\n"
        f"`{PREFIX}investigate <incident_id>` — deep root-cause investigation (traces + logs)\n"
        f"`{PREFIX}dashboards` — list available Grafana dashboards\n"
        f"`{PREFIX}panels <dashboard>` — list a dashboard's panels (id + title) for use with !shot\n"
        f"`{PREFIX}shot <panel_id> [minutes]` — screenshot a panel on the default dashboard\n"
        f"`{PREFIX}shot <dashboard> <panel_id> [minutes]` — screenshot a panel on another dashboard\n"
        f"`{PREFIX}shot <dashboard> [minutes]` — screenshot the WHOLE dashboard\n"
        f"`{PREFIX}incidents` — list recent incidents\n"
        f"`{PREFIX}help` — this message"
    )


def format_dashboards(dashboards: list[dict]) -> str:
    if not dashboards:
        return "No dashboards found."
    lines = ["**Dashboards** (use the uid or a word from the title with `!shot`)"]
    for d in dashboards:
        lines.append(f"`{d.get('uid','')}` · {d.get('title','(untitled)')}")
    return "\n".join(lines)


def chunk_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """Split a long message into Discord-sized chunks on line boundaries."""
    if len(text) <= limit:
        return [text] if text else [""]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single very long line
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


@dataclass(frozen=True, slots=True)
class ShotRequest:
    dashboard: str | None  # uid or title/slug query; None = default dashboard
    panel_id: int | None  # None = whole dashboard
    minutes: int


def _minutes(token: str | None) -> int:
    if token is None:
        return 60
    try:
        return max(1, int(token))
    except ValueError:
        return 60


def _is_int(token: str) -> bool:
    return token.lstrip("-").isdigit()


def parse_shot(args: list[str]) -> ShotRequest | None:
    """Parse `!shot` variants:
    - `!shot <panel_id> [minutes]`            → panel on the default dashboard
    - `!shot <dashboard> <panel_id> [minutes]` → panel on a named dashboard
    - `!shot <dashboard> [minutes]`            → the WHOLE named dashboard
    """
    if not args:
        return None
    if _is_int(args[0]):  # default dashboard, specific panel
        return ShotRequest(None, int(args[0]), _minutes(args[1] if len(args) > 1 else None))
    if len(args) >= 2 and _is_int(args[1]):  # dashboard + panel
        return ShotRequest(args[0], int(args[1]), _minutes(args[2] if len(args) > 2 else None))
    # dashboard only → whole dashboard (optional minutes as the 2nd token)
    return ShotRequest(args[0], None, _minutes(args[1] if len(args) > 1 else None))
