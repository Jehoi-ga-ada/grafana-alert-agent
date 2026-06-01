"""Discord webhook notifier — posts a rich embed with an optional screenshot."""

from __future__ import annotations

import json
import logging

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(15.0, connect=8.0)


class DiscordError(RuntimeError):
    """Raised when the webhook rejects a message."""


class DiscordNotifier:
    """Implements Notifier. The only component that POSTs to an external service."""

    def __init__(self, webhook_url: str, username: str = "Grafana Alert Agent") -> None:
        self._webhook_url = webhook_url
        self._username = username
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send(
        self,
        *,
        embed: dict,
        image_png: bytes | None = None,
        image_name: str = "panel.png",
    ) -> None:
        if not self._webhook_url:
            logger.warning("no Discord webhook configured; skipping notification")
            return

        payload: dict = {"username": self._username, "embeds": [embed]}

        if image_png is not None:
            # Reference the attachment from the embed image.
            embed = {**embed, "image": {"url": f"attachment://{image_name}"}}
            payload["embeds"] = [embed]
            files = {
                "payload_json": (None, json.dumps(payload), "application/json"),
                "files[0]": (image_name, image_png, "image/png"),
            }
            resp = await self._client.post(self._webhook_url, files=files)
        else:
            resp = await self._client.post(self._webhook_url, json=payload)

        if resp.status_code >= 400:
            raise DiscordError(f"webhook returned {resp.status_code}: {resp.text[:200]}")
