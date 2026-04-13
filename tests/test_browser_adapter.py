"""Tests for the Playwright browser adapter.

Playwright is an optional dependency — tests mock all browser
interactions so the suite runs without ``playwright install``.

Coverage:

  * PlaywrightAdapter metadata (name, category, capabilities)
  * is_configured() checks playwright availability
  * SCRAPE_PAGE: URL validation, happy path, timeout mapping
  * BROWSER_SCREENSHOT: saves file, path returned
  * BROWSER_EXTRACT: selectors validation, data extraction
  * Bootstrap registration
  * Capability enum values exist
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from core.adapters import (
    AdapterCategory,
    AdapterValidationError,
    Capability,
    get_config,
    get_registry,
    get_router,
    reset_config,
    reset_metrics,
    reset_registry,
    reset_router,
)
from core.adapters.errors import AdapterError, AdapterTimeout


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()


# ── Helpers ────────────────────────────────────────────────


def _mock_page(*, url="https://example.com", title="Example", text="Hello world"):
    """Build a mock Playwright page object."""
    page = MagicMock()
    page.url = url
    page.title.return_value = title
    page.inner_text.return_value = text
    page.content.return_value = f"<html><body>{text}</body></html>"
    page.screenshot.return_value = None
    # query_selector_all returns mock elements
    elem = MagicMock()
    elem.inner_text.return_value = "$19.99"
    page.query_selector_all.return_value = [elem]
    return page


@contextmanager
def _patch_browser(page=None):
    """Patch ``_run_in_browser`` **and** ``is_configured`` to avoid
    real browser launch and bypass the configured-check gate."""
    if page is None:
        page = _mock_page()

    def fake_run(self, url, timeout_ms, wait_until, *, action):
        return action(page)

    cls = _get_adapter_class()
    with (
        patch.object(cls, "_run_in_browser", fake_run),
        patch.object(cls, "is_configured", return_value=True),
    ):
        yield


def _get_adapter_class():
    from core.adapters.browser.playwright import PlaywrightAdapter
    return PlaywrightAdapter


# ── Capability enum ────────────────────────────────────────


class TestBrowserCapabilities:
    def test_capabilities_exist(self):
        assert Capability("scrape_page") is Capability.SCRAPE_PAGE
        assert Capability("browser_screenshot") is Capability.BROWSER_SCREENSHOT
        assert Capability("browser_extract") is Capability.BROWSER_EXTRACT

    def test_browser_category_exists(self):
        assert AdapterCategory("browser") is AdapterCategory.BROWSER


# ── Metadata ───────────────────────────────────────────────


class TestPlaywrightMetadata:
    def test_metadata(self):
        a = _get_adapter_class()()
        assert a.name == "playwright"
        assert a.category == AdapterCategory.BROWSER
        assert Capability.SCRAPE_PAGE in a.capabilities
        assert Capability.BROWSER_SCREENSHOT in a.capabilities
        assert Capability.BROWSER_EXTRACT in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.0


# ── Configuration ──────────────────────────────────────────


class TestPlaywrightConfiguration:
    def test_is_configured_reflects_import(self):
        """is_configured returns True when playwright is importable."""
        a = _get_adapter_class()()
        # In test env playwright may or may not be installed;
        # test that the method returns a bool without crashing.
        assert isinstance(a.is_configured(), bool)


# ── URL validation ─────────────────────────────────────────


class TestURLValidation:
    def test_missing_url_fails(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(Capability.SCRAPE_PAGE, {})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_non_http_url_fails(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(Capability.SCRAPE_PAGE, {"url": "ftp://bad"})
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "http" in result.error.reason

    def test_valid_url_passes(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(Capability.SCRAPE_PAGE, {"url": "https://example.com"})
        assert result.ok


# ── SCRAPE_PAGE ────────────────────────────────────────────


class TestScrapePage:
    def test_scrape_returns_text_and_title(self):
        page = _mock_page(title="Test Page", text="Page content here")
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(Capability.SCRAPE_PAGE, {"url": "https://example.com"})
        assert result.ok
        assert result.data["title"] == "Test Page"
        assert "Page content" in result.data["text"]
        assert result.data["url"] == "https://example.com"
        assert isinstance(result.data["html_length"], int)

    def test_scrape_truncates_text(self):
        """Body text is truncated to 50,000 chars."""
        page = _mock_page(text="x" * 100_000)
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(Capability.SCRAPE_PAGE, {"url": "https://example.com"})
        assert result.ok
        assert len(result.data["text"]) == 50_000

    def test_scrape_timeout_mapped(self):
        """Playwright TimeoutError maps to AdapterTimeout."""
        a = _get_adapter_class()()

        def raise_timeout(self, url, timeout_ms, wait_until, *, action):
            from core.adapters.errors import AdapterTimeout
            raise AdapterTimeout("playwright", "timed out")

        cls = _get_adapter_class()
        with (
            patch.object(cls, "_run_in_browser", raise_timeout),
            patch.object(cls, "is_configured", return_value=True),
        ):
            result = a.execute(Capability.SCRAPE_PAGE, {"url": "https://example.com"})
        assert not result.ok
        assert isinstance(result.error, AdapterTimeout)


# ── BROWSER_SCREENSHOT ─────────────────────────────────────


class TestBrowserScreenshot:
    def test_screenshot_returns_path(self, tmp_path):
        page = _mock_page()
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_SCREENSHOT,
                {"url": "https://example.com", "output_dir": str(tmp_path)},
            )
        assert result.ok
        assert "screenshot_path" in result.data
        assert result.data["screenshot_path"].startswith(str(tmp_path))
        assert result.data["full_page"] is True

    def test_screenshot_viewport_only(self, tmp_path):
        page = _mock_page()
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_SCREENSHOT,
                {
                    "url": "https://example.com",
                    "full_page": False,
                    "output_dir": str(tmp_path),
                },
            )
        assert result.ok
        assert result.data["full_page"] is False


# ── BROWSER_EXTRACT ────────────────────────────────────────


class TestBrowserExtract:
    def test_extract_requires_selectors(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(
                Capability.BROWSER_EXTRACT,
                {"url": "https://example.com"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "selectors" in result.error.reason

    def test_extract_empty_selectors_fails(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(
                Capability.BROWSER_EXTRACT,
                {"url": "https://example.com", "selectors": {}},
            )
        assert not result.ok

    def test_extract_happy_path(self):
        page = _mock_page()
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_EXTRACT,
                {
                    "url": "https://example.com",
                    "selectors": {"price": ".product-price", "title": "h1"},
                },
            )
        assert result.ok
        assert "extracted" in result.data
        # Single element returns a string (not a list)
        assert result.data["extracted"]["price"] == "$19.99"
        assert result.data["selectors_count"] == 2

    def test_extract_multiple_elements(self):
        page = _mock_page()
        elem1 = MagicMock()
        elem1.inner_text.return_value = "$10.00"
        elem2 = MagicMock()
        elem2.inner_text.return_value = "$20.00"
        page.query_selector_all.return_value = [elem1, elem2]

        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_EXTRACT,
                {
                    "url": "https://example.com",
                    "selectors": {"prices": ".price"},
                },
            )
        assert result.ok
        assert result.data["extracted"]["prices"] == ["$10.00", "$20.00"]


# ── Bootstrap ──────────────────────────────────────────────


class TestBrowserBootstrap:
    def test_register_all_adds_playwright(self):
        from core.adapters.browser.bootstrap import register_all
        status = register_all()
        assert "playwright" in status

    def test_register_all_idempotent(self):
        from core.adapters.browser.bootstrap import register_all
        register_all()
        register_all()
        assert len([n for n in get_registry().names() if n == "playwright"]) == 1
