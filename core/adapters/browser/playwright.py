"""PlaywrightAdapter — headless browser automation via Playwright.

Provides three capabilities the brain can route to:

  * ``SCRAPE_PAGE``        — navigate to a URL, wait for render,
                             return the page's text content and
                             optional CSS-selected snippets.
  * ``BROWSER_SCREENSHOT`` — capture a full-page or viewport
                             screenshot as a PNG file saved to a
                             configurable output directory.
  * ``BROWSER_EXTRACT``    — extract structured data from a
                             rendered page using CSS selectors.

Playwright runs in **headless Chromium** mode by default. No
external service or API key is needed — the browser binary is
bundled with ``playwright install chromium``.

The adapter is best-effort: if ``playwright`` is not installed,
``is_configured()`` returns False and the router silently skips
it. The controller never crashes.

Usage (by the brain, via the router)::

    result = router.execute(
        Capability.SCRAPE_PAGE,
        {"url": "https://example.com", "wait_for": "networkidle"},
    )

Reference: https://playwright.dev/python/docs/api/class-browser
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from ..errors import (
    AdapterError,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False
    sync_playwright = None  # type: ignore[assignment,misc]
    PwTimeout = None  # type: ignore[assignment,misc]

logger = get_logger("adapters.browser.playwright")

_DEFAULT_TIMEOUT_MS = 30_000
_DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class PlaywrightAdapter(BaseAdapter):
    """Headless Chromium browser via Playwright."""

    name = "playwright"
    category = AdapterCategory.BROWSER
    capabilities = {
        Capability.SCRAPE_PAGE,
        Capability.BROWSER_SCREENSHOT,
        Capability.BROWSER_EXTRACT,
    }

    priority = 80
    cost_per_call = 0.0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        """True when the ``playwright`` package is importable.
        No API key needed — Playwright runs a local browser."""
        return _PLAYWRIGHT_AVAILABLE

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability == Capability.SCRAPE_PAGE:
            return self._do_scrape(params)
        if capability == Capability.BROWSER_SCREENSHOT:
            return self._do_screenshot(params)
        if capability == Capability.BROWSER_EXTRACT:
            return self._do_extract(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── SCRAPE_PAGE ────────────────────────────────────────────

    def _do_scrape(self, params: dict[str, Any]) -> AdapterResult:
        url = self._require_url(params)
        timeout = int(params.get("timeout_ms", _DEFAULT_TIMEOUT_MS))
        wait_until = params.get("wait_for", "domcontentloaded")

        page_data = self._run_in_browser(
            url, timeout, wait_until,
            action=lambda page: {
                "url": page.url,
                "title": page.title(),
                "text": page.inner_text("body")[:50_000],
                "html_length": len(page.content()),
            },
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.SCRAPE_PAGE.value,
            data=page_data,
        )

    # ── BROWSER_SCREENSHOT ─────────────────────────────────────

    def _do_screenshot(self, params: dict[str, Any]) -> AdapterResult:
        url = self._require_url(params)
        timeout = int(params.get("timeout_ms", _DEFAULT_TIMEOUT_MS))
        full_page = params.get("full_page", True)
        output_dir = params.get("output_dir", "/tmp/shopai_screenshots")

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        filename = f"screenshot_{int(time.time())}.png"
        filepath = str(Path(output_dir) / filename)

        def take_shot(page):
            page.screenshot(path=filepath, full_page=full_page)
            return {
                "url": page.url,
                "title": page.title(),
                "screenshot_path": filepath,
                "full_page": full_page,
            }

        page_data = self._run_in_browser(
            url, timeout, "domcontentloaded", action=take_shot,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.BROWSER_SCREENSHOT.value,
            data=page_data,
        )

    # ── BROWSER_EXTRACT ────────────────────────────────────────

    def _do_extract(self, params: dict[str, Any]) -> AdapterResult:
        url = self._require_url(params)
        selectors = params.get("selectors", {})
        if not selectors or not isinstance(selectors, dict):
            raise AdapterValidationError(
                self.name,
                "'selectors' dict is required for BROWSER_EXTRACT "
                "(e.g. {\"price\": \".product-price\", \"title\": \"h1\"})",
            )
        timeout = int(params.get("timeout_ms", _DEFAULT_TIMEOUT_MS))

        def extract(page):
            results: dict[str, Any] = {}
            for key, selector in selectors.items():
                try:
                    elements = page.query_selector_all(str(selector))
                    texts = [
                        el.inner_text().strip()
                        for el in elements
                        if el.inner_text().strip()
                    ]
                    results[key] = texts if len(texts) != 1 else texts[0]
                except Exception as exc:  # noqa: BLE001
                    results[key] = {"error": str(exc)}
            return {
                "url": page.url,
                "title": page.title(),
                "extracted": results,
                "selectors_count": len(selectors),
            }

        page_data = self._run_in_browser(
            url, timeout, "domcontentloaded", action=extract,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.BROWSER_EXTRACT.value,
            data=page_data,
        )

    # ── Shared browser context ─────────────────────────────────

    def _run_in_browser(
        self,
        url: str,
        timeout_ms: int,
        wait_until: str,
        *,
        action,
    ) -> dict[str, Any]:
        """Launch a Chromium context, navigate to ``url``, execute
        ``action(page)``, and return the result dict. The browser
        is always closed on exit — no leaked processes.

        Raises typed adapter errors for timeout, unavailability,
        and generic failures.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "playwright not installed",
            )

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    context = browser.new_context(
                        viewport=_DEFAULT_VIEWPORT,
                        user_agent=_DEFAULT_USER_AGENT,
                    )
                    page = context.new_page()
                    page.set_default_timeout(timeout_ms)
                    page.goto(url, wait_until=wait_until, timeout=timeout_ms)
                    result = action(page)
                finally:
                    browser.close()
            return result
        except PwTimeout as exc:
            raise AdapterTimeout(
                self.name, f"page load timeout ({timeout_ms}ms): {exc}",
            ) from exc
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"browser error: {type(exc).__name__}: {exc}",
            ) from exc

    # ── Validation helper ──────────────────────────────────────

    @staticmethod
    def _require_url(params: dict[str, Any]) -> str:
        url = params.get("url")
        if not url or not isinstance(url, str):
            raise AdapterValidationError(
                "playwright", "'url' is required",
            )
        if not url.startswith(("http://", "https://")):
            raise AdapterValidationError(
                "playwright",
                f"'url' must start with http:// or https:// (got {url!r})",
            )
        return url
