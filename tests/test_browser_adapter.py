"""Tests for the Playwright browser adapter.

Playwright is an optional dependency — tests mock all browser
interactions so the suite runs without ``playwright install``.

Coverage:

  * PlaywrightAdapter metadata (name, category, capabilities)
  * is_configured() checks playwright availability
  * SCRAPE_PAGE: URL validation, happy path, timeout mapping
  * BROWSER_SCREENSHOT: saves file, path returned
  * BROWSER_EXTRACT: selectors validation, data extraction
  * BROWSER_CLICK / BROWSER_FILL / BROWSER_WAIT_SELECTOR (new)
  * Captcha detection → CaptchaDetected raised
  * BrowserSession integration path (profile, UA, viewport flow)
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
    CaptchaDetected,
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
    # Ensure each test starts with a fresh BrowserSession singleton.
    from core.adapters.browser.session import BrowserSession
    BrowserSession.reset()
    yield
    reset_config()
    reset_registry()
    reset_metrics()
    reset_router()
    BrowserSession.reset()


# ── Helpers ────────────────────────────────────────────────


def _mock_page(*, url="https://example.com", title="Example", text="Hello world"):
    """Build a mock Playwright page object."""
    page = MagicMock()
    page.url = url
    page.title.return_value = title
    page.inner_text.return_value = text
    page.content.return_value = f"<html><body>{text}</body></html>"
    page.screenshot.return_value = None
    elem = MagicMock()
    elem.inner_text.return_value = "$19.99"
    page.query_selector_all.return_value = [elem]
    return page


@contextmanager
def _patch_browser(page=None):
    """Patch ``_run_in_browser`` **and** ``is_configured`` to avoid
    real browser launch and bypass the configured-check gate.

    Matches the new ``_run_in_browser(url, timeout_ms, wait_until,
    params, *, action)`` signature.
    """
    if page is None:
        page = _mock_page()

    def fake_run(self, url, timeout_ms, wait_until, params, *, action):
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
        assert Capability("browser_click") is Capability.BROWSER_CLICK
        assert Capability("browser_fill") is Capability.BROWSER_FILL
        assert Capability("browser_wait_selector") is Capability.BROWSER_WAIT_SELECTOR

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
        assert Capability.BROWSER_CLICK in a.capabilities
        assert Capability.BROWSER_FILL in a.capabilities
        assert Capability.BROWSER_WAIT_SELECTOR in a.capabilities
        assert a.priority == 80
        assert a.cost_per_call == 0.0


# ── Configuration ──────────────────────────────────────────


class TestPlaywrightConfiguration:
    def test_is_configured_reflects_import(self):
        a = _get_adapter_class()()
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
        page = _mock_page(text="x" * 100_000)
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(Capability.SCRAPE_PAGE, {"url": "https://example.com"})
        assert result.ok
        assert len(result.data["text"]) == 50_000

    def test_scrape_timeout_mapped(self):
        a = _get_adapter_class()()

        def raise_timeout(self, url, timeout_ms, wait_until, params, *, action):
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


# ── BROWSER_CLICK ──────────────────────────────────────────


class TestBrowserClick:
    def test_click_requires_selector(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(
                Capability.BROWSER_CLICK,
                {"url": "https://example.com"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "selector" in result.error.reason

    def test_click_happy_path(self):
        page = _mock_page(title="After Click", url="https://example.com/next")
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_CLICK,
                {"url": "https://example.com", "selector": "button#submit"},
            )
        assert result.ok
        page.wait_for_selector.assert_called_once()
        page.click.assert_called_once()
        assert result.data["clicked"] == "button#submit"
        assert result.data["url"] == "https://example.com/next"

    def test_click_with_wait_after(self):
        page = _mock_page()
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_CLICK,
                {
                    "url": "https://example.com",
                    "selector": ".go",
                    "wait_after": "networkidle",
                },
            )
        assert result.ok
        page.wait_for_load_state.assert_called_once_with(
            "networkidle", timeout=30_000,
        )


# ── BROWSER_FILL ───────────────────────────────────────────


class TestBrowserFill:
    def test_fill_requires_fields(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(
                Capability.BROWSER_FILL,
                {"url": "https://example.com"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)
        assert "fields" in result.error.reason

    def test_fill_empty_fields_fails(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(
                Capability.BROWSER_FILL,
                {"url": "https://example.com", "fields": {}},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_fill_happy_path(self):
        page = _mock_page()
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_FILL,
                {
                    "url": "https://example.com",
                    "fields": {"#email": "a@b.com", "#pw": "secret"},
                },
            )
        assert result.ok
        assert page.fill.call_count == 2
        assert set(result.data["filled"]) == {"#email", "#pw"}
        assert result.data["submitted"] is False

    def test_fill_with_submit(self):
        page = _mock_page()
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_FILL,
                {
                    "url": "https://example.com",
                    "fields": {"#q": "shoes"},
                    "submit_selector": "button[type=submit]",
                },
            )
        assert result.ok
        page.click.assert_called_once_with(
            "button[type=submit]", timeout=30_000,
        )
        assert result.data["submitted"] is True


# ── BROWSER_WAIT_SELECTOR ──────────────────────────────────


class TestBrowserWaitSelector:
    def test_wait_requires_selector(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(
                Capability.BROWSER_WAIT_SELECTOR,
                {"url": "https://example.com"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_wait_invalid_state_fails(self):
        a = _get_adapter_class()()
        with _patch_browser():
            result = a.execute(
                Capability.BROWSER_WAIT_SELECTOR,
                {
                    "url": "https://example.com",
                    "selector": ".x",
                    "state": "bogus",
                },
            )
        assert not result.ok
        assert isinstance(result.error, AdapterValidationError)

    def test_wait_happy_path(self):
        page = _mock_page()
        a = _get_adapter_class()()
        with _patch_browser(page):
            result = a.execute(
                Capability.BROWSER_WAIT_SELECTOR,
                {"url": "https://example.com", "selector": "#loaded"},
            )
        assert result.ok
        page.wait_for_selector.assert_called_once_with(
            "#loaded", state="visible", timeout=30_000,
        )
        assert result.data["selector"] == "#loaded"
        assert result.data["found"] is True


# ── Captcha detection integration ──────────────────────────


class TestCaptchaDetection:
    def test_run_in_browser_raises_on_captcha_page(self, monkeypatch):
        """When the page screams Cloudflare, adapter raises CaptchaDetected."""
        from core.adapters.browser import session as session_mod

        page = _mock_page(
            title="Just a moment...",
            text="cf-chl-bypass",
        )
        # Make content() return html with the marker so detect_captcha hits.
        page.content.return_value = (
            '<html><body><div class="cf-chl-bypass">challenge</div></body></html>'
        )

        class FakeCtxMgr:
            def __enter__(self_inner):
                return page

            def __exit__(self_inner, *_):
                return False

        class FakeSession:
            def acquire_page(self_inner, **_kwargs):
                return FakeCtxMgr()

            def note_captcha(self_inner):
                self_inner.captcha_count = getattr(
                    self_inner, "captcha_count", 0,
                ) + 1

        fake = FakeSession()
        monkeypatch.setattr(
            session_mod.BrowserSession, "instance",
            classmethod(lambda cls, **_: fake),
        )
        # Also patch on the adapter's import site.
        from core.adapters.browser import playwright as pw_mod
        monkeypatch.setattr(
            pw_mod.BrowserSession, "instance",
            classmethod(lambda cls, **_: fake),
        )
        monkeypatch.setattr(pw_mod, "_PLAYWRIGHT_AVAILABLE", True)

        a = _get_adapter_class()()
        with patch.object(_get_adapter_class(), "is_configured", return_value=True):
            result = a.execute(
                Capability.SCRAPE_PAGE, {"url": "https://shielded.example.com"},
            )
        assert not result.ok
        assert isinstance(result.error, CaptchaDetected)
        assert result.error.provider == "cloudflare"
        assert fake.captcha_count == 1

    def test_allow_captcha_bypasses_check(self, monkeypatch):
        """With allow_captcha=True, challenge HTML is returned as normal data."""
        from core.adapters.browser import playwright as pw_mod

        page = _mock_page(
            title="Just a moment...",
            text="Verifying you are human...",
        )
        page.content.return_value = '<html><body>cf-chl-bypass</body></html>'

        class FakeCtxMgr:
            def __enter__(self_inner):
                return page

            def __exit__(self_inner, *_):
                return False

        class FakeSession:
            def acquire_page(self_inner, **_kwargs):
                return FakeCtxMgr()

            def note_captcha(self_inner):
                pass

        fake = FakeSession()
        monkeypatch.setattr(
            pw_mod.BrowserSession, "instance",
            classmethod(lambda cls, **_: fake),
        )
        monkeypatch.setattr(pw_mod, "_PLAYWRIGHT_AVAILABLE", True)

        a = _get_adapter_class()()
        with patch.object(_get_adapter_class(), "is_configured", return_value=True):
            result = a.execute(
                Capability.SCRAPE_PAGE,
                {
                    "url": "https://shielded.example.com",
                    "allow_captcha": True,
                },
            )
        assert result.ok


# ── BrowserSession integration ─────────────────────────────


class TestResponseStatus:
    """Self-critique fix: expose response_status/response_ok so
    callers can tell 'scraped a 404 page' from 'scraped the real
    thing'. Raise loudly when goto returns no response at all."""

    def test_response_status_attached_to_data(self, monkeypatch):
        from core.adapters.browser import playwright as pw_mod

        page = _mock_page()
        # Neutralise captcha detection (default mock html is clean
        # but ensure no marker).
        page.content.return_value = "<html><body>ok</body></html>"
        response = MagicMock()
        response.status = 200
        response.ok = True
        page.goto.return_value = response

        class FakeCtxMgr:
            def __enter__(self_inner):
                return page

            def __exit__(self_inner, *_):
                return False

        class FakeSession:
            def acquire_page(self_inner, **_kwargs):
                return FakeCtxMgr()

            def note_captcha(self_inner):
                pass

        fake = FakeSession()
        monkeypatch.setattr(
            pw_mod.BrowserSession, "instance",
            classmethod(lambda cls, **_: fake),
        )
        monkeypatch.setattr(pw_mod, "_PLAYWRIGHT_AVAILABLE", True)

        a = _get_adapter_class()()
        with patch.object(_get_adapter_class(), "is_configured", return_value=True):
            result = a.execute(
                Capability.SCRAPE_PAGE, {"url": "https://example.com"},
            )
        assert result.ok
        assert result.data["response_status"] == 200
        assert result.data["response_ok"] is True

    def test_raises_when_goto_returns_none(self, monkeypatch):
        """Playwright returns None on network-level failures (DNS
        error, aborted redirect). Adapter must surface this as a
        hard AdapterError instead of returning an empty scrape."""
        from core.adapters.browser import playwright as pw_mod

        page = _mock_page()
        page.goto.return_value = None

        class FakeCtxMgr:
            def __enter__(self_inner):
                return page

            def __exit__(self_inner, *_):
                return False

        class FakeSession:
            def acquire_page(self_inner, **_kwargs):
                return FakeCtxMgr()

            def note_captcha(self_inner):
                pass

        fake = FakeSession()
        monkeypatch.setattr(
            pw_mod.BrowserSession, "instance",
            classmethod(lambda cls, **_: fake),
        )
        monkeypatch.setattr(pw_mod, "_PLAYWRIGHT_AVAILABLE", True)

        a = _get_adapter_class()()
        with patch.object(_get_adapter_class(), "is_configured", return_value=True):
            result = a.execute(
                Capability.SCRAPE_PAGE, {"url": "https://nowhere.example/"},
            )
        assert not result.ok
        assert isinstance(result.error, AdapterError)
        assert "no response" in result.error.reason


class TestBrowserSessionIntegration:
    def test_profile_passed_to_session(self, monkeypatch):
        """Adapter forwards ``profile`` / ``user_agent`` / ``viewport``
        into BrowserSession.acquire_page()."""
        from core.adapters.browser import playwright as pw_mod

        acquired: dict = {}
        page = _mock_page()

        class FakeCtxMgr:
            def __enter__(self_inner):
                return page

            def __exit__(self_inner, *_):
                return False

        class FakeSession:
            def acquire_page(self_inner, **kwargs):
                acquired.update(kwargs)
                return FakeCtxMgr()

            def note_captcha(self_inner):
                pass

        # Neutralise captcha check so it doesn't hit the markers
        # in the default mock text.
        page.content.return_value = "<html><body>fine</body></html>"
        page.title.return_value = "Fine"

        fake = FakeSession()
        monkeypatch.setattr(
            pw_mod.BrowserSession, "instance",
            classmethod(lambda cls, **_: fake),
        )
        monkeypatch.setattr(pw_mod, "_PLAYWRIGHT_AVAILABLE", True)

        a = _get_adapter_class()()
        with patch.object(_get_adapter_class(), "is_configured", return_value=True):
            a.execute(
                Capability.SCRAPE_PAGE,
                {
                    "url": "https://example.com",
                    "profile": "shopify-main",
                    "user_agent": "CustomUA/1.0",
                    "viewport": {"width": 800, "height": 600},
                    "timeout_ms": 12345,
                },
            )

        assert acquired["profile"] == "shopify-main"
        assert acquired["user_agent"] == "CustomUA/1.0"
        assert acquired["viewport"] == {"width": 800, "height": 600}
        assert acquired["timeout_ms"] == 12345


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
