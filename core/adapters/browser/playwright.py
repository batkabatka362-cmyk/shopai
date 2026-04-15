"""PlaywrightAdapter — headless browser automation via Playwright.

Provides six capabilities the brain can route to:

  * ``SCRAPE_PAGE``           — navigate to a URL, wait for render,
                                 return the page's text content.
  * ``BROWSER_SCREENSHOT``    — capture a full-page or viewport
                                 PNG saved to an output directory.
  * ``BROWSER_EXTRACT``       — extract structured data from a
                                 rendered page using CSS selectors.
  * ``BROWSER_CLICK``         — click a selector on a page and
                                 return the resulting URL/title.
  * ``BROWSER_FILL``          — fill form fields by selector and
                                 optionally submit.
  * ``BROWSER_WAIT_SELECTOR`` — navigate + block until a selector
                                 appears (or times out).

Backed by ``BrowserSession`` so Chromium is launched once and
reused. Each call picks up a *profile* (default ``"default"``)
whose cookies, UA, and storage persist across calls — the
controller can crawl an auth-walled site without re-logging-in
on every hit.

Every navigation is guarded by a captcha check: if the page looks
like a Cloudflare / hCaptcha / reCAPTCHA challenge, the adapter
raises ``CaptchaDetected`` instead of silently returning the
challenge HTML as a "successful" scrape.

Best-effort: if ``playwright`` is not installed, ``is_configured()``
returns False and the router silently skips the adapter. The
controller never crashes.

Usage (via the router)::

    result = router.execute(
        Capability.SCRAPE_PAGE,
        {
            "url": "https://example.com",
            "profile": "shopify-main",
            "timeout_ms": 30000,
        },
    )
"""
from __future__ import annotations

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
    CaptchaDetected,
)
from .session import BrowserSession
from .stealth import detect_captcha

try:
    from playwright.sync_api import TimeoutError as PwTimeout
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PLAYWRIGHT_AVAILABLE = False
    PwTimeout = None  # type: ignore[assignment,misc]

logger = get_logger("adapters.browser.playwright")

_DEFAULT_TIMEOUT_MS = 30_000


class PlaywrightAdapter(BaseAdapter):
    """Headless Chromium browser via Playwright + BrowserSession."""

    name = "playwright"
    category = AdapterCategory.BROWSER
    capabilities = {
        Capability.SCRAPE_PAGE,
        Capability.BROWSER_SCREENSHOT,
        Capability.BROWSER_EXTRACT,
        Capability.BROWSER_CLICK,
        Capability.BROWSER_FILL,
        Capability.BROWSER_WAIT_SELECTOR,
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
        if capability == Capability.BROWSER_CLICK:
            return self._do_click(params)
        if capability == Capability.BROWSER_FILL:
            return self._do_fill(params)
        if capability == Capability.BROWSER_WAIT_SELECTOR:
            return self._do_wait_selector(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── SCRAPE_PAGE ────────────────────────────────────────────

    def _do_scrape(self, params: dict[str, Any]) -> AdapterResult:
        url = self._require_url(params)
        timeout = int(params.get("timeout_ms", _DEFAULT_TIMEOUT_MS))
        wait_until = params.get("wait_for", "domcontentloaded")

        page_data = self._run_in_browser(
            url, timeout, wait_until, params,
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
            url, timeout, "domcontentloaded", params, action=take_shot,
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
            url, timeout, "domcontentloaded", params, action=extract,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.BROWSER_EXTRACT.value,
            data=page_data,
        )

    # ── BROWSER_CLICK ──────────────────────────────────────────

    def _do_click(self, params: dict[str, Any]) -> AdapterResult:
        url = self._require_url(params)
        selector = self._require_str(params, "selector")
        timeout = int(params.get("timeout_ms", _DEFAULT_TIMEOUT_MS))

        def click(page):
            page.wait_for_selector(selector, timeout=timeout)
            page.click(selector, timeout=timeout)
            # Give the resulting navigation/DOM change a beat to
            # settle. The caller can override wait_for by passing
            # "networkidle" in params["wait_after"].
            wait_after = params.get("wait_after")
            if wait_after:
                page.wait_for_load_state(wait_after, timeout=timeout)
            return {
                "url": page.url,
                "title": page.title(),
                "clicked": selector,
            }

        page_data = self._run_in_browser(
            url, timeout, "domcontentloaded", params, action=click,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.BROWSER_CLICK.value,
            data=page_data,
        )

    # ── BROWSER_FILL ───────────────────────────────────────────

    def _do_fill(self, params: dict[str, Any]) -> AdapterResult:
        url = self._require_url(params)
        fields = params.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise AdapterValidationError(
                self.name,
                "'fields' dict is required for BROWSER_FILL "
                "(e.g. {\"#email\": \"a@b.com\", \"#password\": \"...\"})",
            )
        submit_selector = params.get("submit_selector")
        timeout = int(params.get("timeout_ms", _DEFAULT_TIMEOUT_MS))

        def fill(page):
            filled: list[str] = []
            for selector, value in fields.items():
                page.wait_for_selector(str(selector), timeout=timeout)
                page.fill(str(selector), str(value), timeout=timeout)
                filled.append(str(selector))
            if submit_selector:
                page.click(str(submit_selector), timeout=timeout)
                page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return {
                "url": page.url,
                "title": page.title(),
                "filled": filled,
                "submitted": bool(submit_selector),
            }

        page_data = self._run_in_browser(
            url, timeout, "domcontentloaded", params, action=fill,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.BROWSER_FILL.value,
            data=page_data,
        )

    # ── BROWSER_WAIT_SELECTOR ──────────────────────────────────

    def _do_wait_selector(self, params: dict[str, Any]) -> AdapterResult:
        url = self._require_url(params)
        selector = self._require_str(params, "selector")
        state = params.get("state", "visible")
        if state not in ("attached", "detached", "visible", "hidden"):
            raise AdapterValidationError(
                self.name,
                f"'state' must be attached|detached|visible|hidden "
                f"(got {state!r})",
            )
        timeout = int(params.get("timeout_ms", _DEFAULT_TIMEOUT_MS))

        def wait(page):
            page.wait_for_selector(selector, state=state, timeout=timeout)
            return {
                "url": page.url,
                "title": page.title(),
                "selector": selector,
                "state": state,
                "found": True,
            }

        page_data = self._run_in_browser(
            url, timeout, "domcontentloaded", params, action=wait,
        )
        return AdapterResult.success(
            adapter=self.name,
            capability=Capability.BROWSER_WAIT_SELECTOR.value,
            data=page_data,
        )

    # ── Shared browser context ─────────────────────────────────

    def _run_in_browser(
        self,
        url: str,
        timeout_ms: int,
        wait_until: str,
        params: dict[str, Any],
        *,
        action,
    ) -> dict[str, Any]:
        """Acquire a page via ``BrowserSession``, navigate to
        ``url``, check for captcha walls, run ``action(page)``,
        and return the result dict.

        Raises typed adapter errors for timeout, unavailability,
        captcha, and generic failures.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "playwright not installed",
            )

        profile = str(params.get("profile") or "default")
        user_agent = params.get("user_agent") or None
        viewport = params.get("viewport") or None

        session = BrowserSession.instance()
        try:
            with session.acquire_page(
                profile=profile,
                user_agent=user_agent,
                viewport=viewport,
                timeout_ms=timeout_ms,
            ) as page:
                page.goto(url, wait_until=wait_until, timeout=timeout_ms)

                # Guard: did we land on a bot challenge page?
                # Skip the check if caller explicitly expects one
                # (e.g. a solver is wired in upstream).
                if not params.get("allow_captcha"):
                    provider = self._maybe_detect_captcha(page)
                    if provider is not None:
                        session.note_captcha()
                        raise CaptchaDetected(
                            self.name,
                            f"bot challenge page: {provider}",
                            provider=provider,
                            url=page.url,
                        )

                return action(page)
        except CaptchaDetected:
            raise
        except PwTimeout as exc:  # type: ignore[misc]
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

    @staticmethod
    def _maybe_detect_captcha(page) -> str | None:
        """Defensive captcha probe — any error reading the page is
        swallowed (we'd rather scrape than false-positive)."""
        try:
            title = page.title() or ""
            url = page.url or ""
            # Body content read is optional; some sites delay
            # render past the initial DOM.
            try:
                html = page.content()
            except Exception:  # noqa: BLE001
                html = ""
            return detect_captcha(title=title, html=html, url=url)
        except Exception:  # noqa: BLE001
            return None

    # ── Validation helpers ─────────────────────────────────────

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

    @staticmethod
    def _require_str(params: dict[str, Any], key: str) -> str:
        value = params.get(key)
        if not value or not isinstance(value, str):
            raise AdapterValidationError(
                "playwright", f"'{key}' is required (str)",
            )
        return value
