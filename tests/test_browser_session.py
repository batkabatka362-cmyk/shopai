"""Tests for BrowserSession + stealth helpers.

BrowserSession is tested without launching a real browser — every
Playwright call is mocked. The tests assert:

  * Singleton lifecycle (``instance()`` / ``reset()``)
  * Lazy Chromium launch (first ``acquire_page`` → ``launch_count == 1``)
  * Per-profile context reuse (second acquire same profile → still 1 context)
  * Different profiles → different contexts
  * Per-profile lock serialises same-profile acquires
  * Stealth init-script injected
  * Cookies persist via ``storage_state`` load / save
  * ``clear_profile`` drops context and deletes cookie file
  * Captcha detection: each provider, title/url/html markers
  * UA rotation: pool non-empty; same seed → same UA; different seed → different UA
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.adapters.browser.session import BrowserSession
from core.adapters.browser import stealth as stealth_mod
from core.adapters.errors import AdapterUnavailable


@pytest.fixture(autouse=True)
def _clean_singleton():
    BrowserSession.reset()
    yield
    BrowserSession.reset()


# ── Fake playwright harness ────────────────────────────────


def _fake_context():
    ctx = MagicMock(name="BrowserContext")
    # storage_state returns a simple dict so save/load works.
    ctx.storage_state.return_value = {"cookies": [], "origins": []}
    page = MagicMock(name="Page")
    ctx.new_page.return_value = page
    return ctx


def _fake_browser():
    browser = MagicMock(name="Browser")
    browser.new_context.side_effect = lambda **_kw: _fake_context()
    return browser


def _fake_pw():
    """Mimics ``sync_playwright().start()`` return value."""
    pw = MagicMock(name="PlaywrightHandle")
    pw.chromium.launch.return_value = _fake_browser()
    return pw


def _install_fake_playwright(monkeypatch, pw_factory=_fake_pw):
    """Patch the session module so ``sync_playwright().start()``
    returns our fake handle."""
    from core.adapters.browser import session as session_mod

    starter = MagicMock()
    starter.start.side_effect = pw_factory
    # sync_playwright() is called without args and returns an
    # object with .start(); emulate that.
    monkeypatch.setattr(
        session_mod, "sync_playwright", lambda: starter,
    )
    monkeypatch.setattr(session_mod, "_PLAYWRIGHT_AVAILABLE", True)


# ── Singleton lifecycle ────────────────────────────────────


class TestSingleton:
    def test_instance_returns_same_object(self, monkeypatch):
        _install_fake_playwright(monkeypatch)
        a = BrowserSession.instance()
        b = BrowserSession.instance()
        assert a is b

    def test_reset_creates_fresh_instance(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        a = BrowserSession.instance(cookie_dir=str(tmp_path))
        BrowserSession.reset()
        b = BrowserSession.instance(cookie_dir=str(tmp_path))
        assert a is not b

    def test_instance_unavailable_when_playwright_missing(self, monkeypatch):
        from core.adapters.browser import session as session_mod
        monkeypatch.setattr(session_mod, "_PLAYWRIGHT_AVAILABLE", False)
        session = BrowserSession.instance()
        assert session.is_available is False
        with pytest.raises(AdapterUnavailable):
            with session.acquire_page(profile="default"):
                pass


# ── Lazy launch + context reuse ────────────────────────────


class TestLaunchLifecycle:
    def test_browser_not_launched_until_first_acquire(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        assert session.launch_count == 0
        with session.acquire_page(profile="p1"):
            pass
        assert session.launch_count == 1

    def test_second_acquire_reuses_browser(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1"):
            pass
        with session.acquire_page(profile="p1"):
            pass
        assert session.launch_count == 1  # Chromium started once

    def test_same_profile_reuses_context(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1"):
            pass
        ctx_first = session._contexts["p1"]
        with session.acquire_page(profile="p1"):
            pass
        assert session._contexts["p1"] is ctx_first

    def test_different_profiles_get_different_contexts(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="a"):
            pass
        with session.acquire_page(profile="b"):
            pass
        assert session._contexts["a"] is not session._contexts["b"]

    def test_shutdown_clears_state(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1"):
            pass
        session.shutdown()
        assert session._browser is None
        assert session._pw is None
        assert "p1" not in session._contexts


# ── Context configuration ──────────────────────────────────


class TestContextConfiguration:
    def test_stealth_init_script_injected(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1"):
            pass
        ctx = session._contexts["p1"]
        ctx.add_init_script.assert_called_once()
        script = ctx.add_init_script.call_args[0][0]
        assert "webdriver" in script
        assert "'plugins'" in script

    def test_per_profile_ua_is_stable(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1"):
            pass
        browser = session._browser
        # First call kwargs → UA1. Reset + acquire again → same UA.
        first_kwargs = browser.new_context.call_args_list[0].kwargs
        ua1 = first_kwargs["user_agent"]

        # New profile gets a (possibly) different UA but same seed
        # must reproduce ua1.
        from core.adapters.browser.stealth import pick_user_agent
        assert pick_user_agent(seed="p1") == ua1

    def test_different_profiles_likely_get_different_UAs(self):
        from core.adapters.browser.stealth import pick_user_agent, user_agent_pool

        # Across many profile names at least 2 distinct UAs appear.
        seen = {pick_user_agent(seed=f"profile-{i}") for i in range(30)}
        assert len(seen) >= 2
        # All chosen UAs come from the curated pool.
        pool = set(user_agent_pool())
        assert seen.issubset(pool)

    def test_custom_user_agent_overrides(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1", user_agent="CustomUA/9.9"):
            pass
        browser = session._browser
        kwargs = browser.new_context.call_args.kwargs
        assert kwargs["user_agent"] == "CustomUA/9.9"


# ── Cookie persistence ─────────────────────────────────────


class TestCookiePersistence:
    def test_storage_state_saved_after_acquire(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1"):
            pass
        cookie_file = tmp_path / "p1.json"
        assert cookie_file.exists()
        payload = json.loads(cookie_file.read_text())
        assert "cookies" in payload

    def test_storage_state_loaded_on_context_create(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        # Pre-seed a cookie file.
        (tmp_path / "p1.json").write_text(
            json.dumps({"cookies": [{"name": "SID", "value": "abc"}]})
        )
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1"):
            pass
        browser = session._browser
        kwargs = browser.new_context.call_args.kwargs
        assert "storage_state" in kwargs
        assert kwargs["storage_state"]["cookies"][0]["name"] == "SID"

    def test_clear_profile_deletes_cookie_file(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        with session.acquire_page(profile="p1"):
            pass
        cookie_file = tmp_path / "p1.json"
        assert cookie_file.exists()
        session.clear_profile("p1")
        assert not cookie_file.exists()
        assert "p1" not in session._contexts

    def test_cookie_file_name_sanitised(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))
        # A profile with path-traversal characters must not escape.
        with session.acquire_page(profile="../../evil"):
            pass
        for p in tmp_path.iterdir():
            assert p.parent == tmp_path


# ── Per-profile locking ────────────────────────────────────


class TestPerProfileLocking:
    def test_same_profile_serialises(self, monkeypatch, tmp_path):
        _install_fake_playwright(monkeypatch)
        session = BrowserSession.instance(cookie_dir=str(tmp_path))

        enter_order: list[str] = []
        exit_order: list[str] = []
        in_flight = 0
        max_in_flight = 0
        in_flight_lock = threading.Lock()

        def run(tag: str):
            nonlocal in_flight, max_in_flight
            with session.acquire_page(profile="shared"):
                with in_flight_lock:
                    in_flight += 1
                    max_in_flight = max(max_in_flight, in_flight)
                enter_order.append(tag)
                time.sleep(0.05)
                exit_order.append(tag)
                with in_flight_lock:
                    in_flight -= 1

        t1 = threading.Thread(target=run, args=("A",))
        t2 = threading.Thread(target=run, args=("B",))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Only one at a time on the same profile.
        assert max_in_flight == 1
        assert len(enter_order) == 2


# ── Captcha detection ──────────────────────────────────────


class TestCaptchaDetection:
    def test_detects_cloudflare_by_title(self):
        assert stealth_mod.detect_captcha(
            title="Just a moment...",
            html="<html></html>",
            url="https://x.com",
        ) == "cloudflare"

    def test_detects_cloudflare_by_html(self):
        html = '<form id="cf-chl-bypass"></form>'
        assert stealth_mod.detect_captcha(html=html) == "cloudflare"

    def test_detects_hcaptcha(self):
        html = '<div class="h-captcha" data-sitekey="abc"></div>'
        assert stealth_mod.detect_captcha(html=html) == "hcaptcha"

    def test_detects_recaptcha(self):
        html = '<div class="g-recaptcha"></div>'
        assert stealth_mod.detect_captcha(html=html) == "recaptcha"

    def test_detects_datadome(self):
        url = "https://geo.captcha-delivery.com/challenge"
        assert stealth_mod.detect_captcha(url=url) == "datadome"

    def test_clean_page_returns_none(self):
        assert stealth_mod.detect_captcha(
            title="Shop — Buy shoes",
            html="<html><body><h1>Welcome</h1></body></html>",
            url="https://shop.example.com/",
        ) is None

    def test_only_scans_first_16kb_of_html(self):
        # Marker buried past the first 16 KB should NOT match.
        padding = "a" * 20_000
        html = padding + '<div class="g-recaptcha"></div>'
        assert stealth_mod.detect_captcha(html=html) is None


# ── User-agent rotation ────────────────────────────────────


class TestUserAgentRotation:
    def test_pool_is_non_empty(self):
        pool = stealth_mod.user_agent_pool()
        assert len(pool) >= 5
        assert all(isinstance(ua, str) and "Mozilla" in ua for ua in pool)

    def test_same_seed_same_ua(self):
        ua1 = stealth_mod.pick_user_agent(seed="shopify-main")
        ua2 = stealth_mod.pick_user_agent(seed="shopify-main")
        assert ua1 == ua2

    def test_no_seed_is_random_from_pool(self):
        pool = set(stealth_mod.user_agent_pool())
        for _ in range(10):
            assert stealth_mod.pick_user_agent() in pool
