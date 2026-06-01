"""Tiny time helpers. The clock is always injected for testability."""

from __future__ import annotations

from datetime import datetime, timezone


def iso(now: float) -> str:
    """ISO-8601 UTC timestamp for a Discord embed."""
    return datetime.fromtimestamp(now, tz=timezone.utc).isoformat()


SECONDS_PER_DAY = 86_400
