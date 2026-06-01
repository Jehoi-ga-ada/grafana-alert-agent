"""Playwright browser lifecycle — launched once, reused across captures.

Excluded from the coverage gate (real-browser glue). Authenticates page loads
with the Grafana service-account token via an Authorization header, so no login
form is needed. TLS to the internal-CA host is tolerated at the browser context.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class BrowserManager:  # pragma: no cover
    def __init__(self, token: str) -> None:
        self._token = token
        self._playwright = None
        self._browser = None
        self._context = None

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        self._context = await self._browser.new_context(
            ignore_https_errors=True,  # internal CA; metrics path still verifies via httpx
            viewport={"width": 1100, "height": 520},
            extra_http_headers={"Authorization": f"Bearer {self._token}"},
        )

    async def new_page(self):
        if self._context is None:
            raise RuntimeError("BrowserManager not started")
        return await self._context.new_page()

    async def stop(self) -> None:
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning("error closing browser: %s", exc)
