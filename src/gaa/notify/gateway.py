"""Discord gateway notifier — posts alerts via the bot client and opens a thread
per incident. Used under `gaa bot` so alert follow-ups stay in their own thread.
Falls back silently if the client/channel isn't ready (the incident is still recorded).
(Excluded from the coverage gate — live Discord I/O.)"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


class GatewayNotifier:  # pragma: no cover - live Discord I/O
    """Implements Notifier (.send) plus .post_alert that returns a thread id."""

    def __init__(self, client, channel_id: int) -> None:
        self._client = client
        self._channel_id = channel_id

    def _channel(self):
        return self._client.get_channel(self._channel_id) if self._channel_id else None

    def _file(self, image_png: bytes | None, image_name: str):
        import discord

        return discord.File(io.BytesIO(image_png), filename=image_name) if image_png else None

    async def send(self, *, embed: dict, image_png: bytes | None = None, image_name: str = "panel.png") -> None:
        import discord

        channel = self._channel()
        if channel is None:
            logger.warning("gateway channel %s not available; dropping message", self._channel_id)
            return
        file = self._file(image_png, image_name)
        await channel.send(embed=discord.Embed.from_dict(embed), files=[file] if file else [])

    async def post_alert(
        self, *, embed: dict, image_png: bytes | None, image_name: str, thread_name: str
    ) -> str | None:
        import discord

        channel = self._channel()
        if channel is None:
            logger.warning("gateway channel %s not available; alert not posted to thread", self._channel_id)
            return None
        file = self._file(image_png, image_name)
        msg = await channel.send(embed=discord.Embed.from_dict(embed), files=[file] if file else [])
        try:
            thread = await msg.create_thread(name=thread_name[:90])
            return str(thread.id)
        except Exception as exc:
            logger.warning("could not create incident thread: %s", exc)
            return None
