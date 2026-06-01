"""Per-request screenshot collector.

The capture tool runs inside the LangGraph agent and can't return image bytes
through the LLM. Instead it stashes PNGs in a ScreenshotCollector bound to the
current request via a ContextVar; the bot drains it after the agent finishes and
attaches the images to the Discord reply. ContextVars propagate through the
agent's async tasks, so the once-built agent still sees the per-message collector.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, field

_current: ContextVar["ScreenshotCollector | None"] = ContextVar("gaa_screenshots", default=None)


@dataclass
class ScreenshotCollector:
    items: list[tuple[str, bytes]] = field(default_factory=list)

    def add(self, name: str, png: bytes) -> None:
        self.items.append((name, png))

    def drain(self) -> list[tuple[str, bytes]]:
        out = list(self.items)
        self.items.clear()
        return out


def set_collector(collector: ScreenshotCollector) -> Token:
    return _current.set(collector)


def reset_collector(token: Token) -> None:
    _current.reset(token)


def get_collector() -> "ScreenshotCollector | None":
    return _current.get()
