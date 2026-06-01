"""Capturer implementations: Playwright (real) and Null (disabled/fallback)."""

from __future__ import annotations

import logging

from gaa.clients.links import dsolo_url
from gaa.domain.models import TimeWindow
from gaa.screenshot.browser import BrowserManager

logger = logging.getLogger(__name__)

_PANEL_READY_SELECTOR = "canvas, .panel-content, [data-panelid], .flot-base"
_NAV_TIMEOUT_MS = 30_000
_RENDER_SETTLE_MS = 1_500


# Injected CSS to hide the app chrome (nav + top bar) and any modal/announcement
# overlay. `display:none` survives React re-renders (unlike removing nodes), and is
# version-tolerant — it doesn't depend on kiosk mode actually applying.
_HIDE_CHROME_CSS = """
  nav, header,
  [aria-label="Main menu"], [class*="MegaMenu" i], [class*="AppChrome" i] header,
  [class*="NavToolbar" i], [class*="PageToolbar" i] { display: none !important; }
  /* Grafana renders modals + their dimming backdrop into the portal container —
     hiding it removes the dialog AND the translucent backdrop that dims the page. */
  #grafana-portal-container,
  [role="dialog"], [aria-modal="true"],
  [class*="modalBackdrop" i], [class*="Backdrop" i] { display: none !important; }
"""

_CLOSE_SELECTORS = (
    'button[aria-label="Close"]',
    '[data-testid="data-testid Modal close"]',
    'button[aria-label="Close dialog"]',
)


async def _dismiss_overlays(page) -> None:  # pragma: no cover - browser glue
    """Close onboarding/announcement modals + hide app chrome before screenshotting."""
    for selector in _CLOSE_SELECTORS:
        try:
            await page.click(selector, timeout=1500)
            break
        except Exception:
            continue
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        await page.add_style_tag(content=_HIDE_CHROME_CSS)
    except Exception as exc:
        logger.debug("overlay/chrome hide failed (continuing): %s", exc)


class NullCapturer:
    """No-op Capturer — used when screenshots are disabled. Implements Capturer."""

    async def capture_panel(
        self,
        panel_id: int,
        window: TimeWindow,
        dashboard_uid: str | None = None,
        dashboard_slug: str | None = None,
    ) -> bytes | None:
        return None

    async def capture_dashboard(
        self, window: TimeWindow, dashboard_uid: str, dashboard_slug: str | None = None
    ) -> bytes | None:
        return None


class PlaywrightCapturer:  # pragma: no cover - exercised only via e2e marker
    """Renders a Grafana d-solo panel page in a headless browser and screenshots it."""

    def __init__(
        self,
        browser: BrowserManager,
        base_url: str,
        dashboard_uid: str,
        dashboard_slug: str,
        theme: str = "dark",
    ) -> None:
        self._browser = browser
        self._base_url = base_url
        self._uid = dashboard_uid
        self._slug = dashboard_slug
        self._theme = theme

    async def capture_panel(
        self,
        panel_id: int,
        window: TimeWindow,
        dashboard_uid: str | None = None,
        dashboard_slug: str | None = None,
    ) -> bytes | None:
        uid = dashboard_uid or self._uid
        slug = dashboard_slug or self._slug or "d"
        if not uid:
            logger.warning("no dashboard UID; cannot capture panel %s", panel_id)
            return None
        url = dsolo_url(self._base_url, uid, slug, panel_id, window, self._theme)
        page = None
        try:
            page = await self._browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
            try:
                await page.wait_for_selector(_PANEL_READY_SELECTOR, timeout=8_000)
            except Exception:
                logger.debug("panel selector not found; screenshotting anyway")
            await page.wait_for_timeout(_RENDER_SETTLE_MS)
            return await page.screenshot(type="png")
        except Exception as exc:
            logger.warning("screenshot of panel %s failed: %s", panel_id, exc)
            return None
        finally:
            if page is not None:
                await page.close()

    async def capture_dashboard(
        self, window: TimeWindow, dashboard_uid: str, dashboard_slug: str | None = None
    ) -> bytes | None:
        from gaa.clients.links import dashboard_url

        uid = dashboard_uid or self._uid
        slug = dashboard_slug or self._slug or "d"
        if not uid:
            return None
        url = dashboard_url(self._base_url, uid, slug, window, self._theme)
        page = None
        try:
            page = await self._browser.new_page()
            await page.set_viewport_size({"width": 1400, "height": 900})
            await page.goto(url, wait_until="networkidle", timeout=_NAV_TIMEOUT_MS)
            try:
                await page.wait_for_selector(_PANEL_READY_SELECTOR, timeout=8_000)
            except Exception:
                logger.debug("dashboard panels not found; screenshotting anyway")
            await _dismiss_overlays(page)
            await page.wait_for_timeout(_RENDER_SETTLE_MS * 2)
            return await page.screenshot(type="png", full_page=True)
        except Exception as exc:
            logger.warning("screenshot of dashboard %s failed: %s", uid, exc)
            return None
        finally:
            if page is not None:
                await page.close()
