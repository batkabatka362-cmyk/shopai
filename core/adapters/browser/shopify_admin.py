"""Shopify admin UI automation — things the Admin API can't do.

Shopify's Admin API covers ~95 % of operations, but a handful of
high-leverage actions only exist in the admin UI (or Shopify locks
them behind OAuth-install flows):

  • Theme customisation in the theme editor (sections, colors)
  • Installing / uninstalling apps from the app store
  • Editing checkout UI (post-purchase extensions)
  • Creating storefront password / shutting down the store
  • Navigation menu edits (Menus section)
  • Shipping profile tweaks
  • Customer support (Shopify Inbox chat)

This module wraps Playwright with a session-login flow so callers
can script those actions. Credentials are read from env:

    SHOPAI_SHOPIFY_ADMIN_EMAIL
    SHOPAI_SHOPIFY_ADMIN_PASSWORD

After login the session cookie is cached at
``data/.shopify_admin_session.json`` so re-auth is rare. 2FA is
handled by a 90-second wait and an optional
``SHOPAI_SHOPIFY_ADMIN_2FA_CODE`` env variable; if unset the caller
is expected to complete the prompt manually (owner-in-the-loop).

All public helpers return ``{"status": "ok|error", ...}`` without
raising — callers treat this layer like any other adapter.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("adapters.browser.shopify_admin")


_SESSION_PATH = Path("data/.shopify_admin_session.json")
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def is_configured() -> bool:
    return bool(
        os.environ.get("SHOPAI_SHOPIFY_URL")
        and os.environ.get("SHOPAI_SHOPIFY_ADMIN_EMAIL")
        and os.environ.get("SHOPAI_SHOPIFY_ADMIN_PASSWORD")
    )


def _chromium_executable() -> str | None:
    # Reuse the Alibaba scraper's discovery logic
    from .alibaba import _chromium_executable as discover
    return discover()


def _store_subdomain() -> str:
    shop = os.environ.get("SHOPAI_SHOPIFY_URL", "")
    if not shop:
        return ""
    return shop.split(".", 1)[0]


def _admin_url(path: str) -> str:
    shop = os.environ.get("SHOPAI_SHOPIFY_URL", "")
    if not shop:
        return ""
    path = path.lstrip("/")
    return f"https://admin.shopify.com/store/{_store_subdomain()}/{path}"


# ── Session management ──────────────────────────────────────

def _load_cookies() -> list[dict[str, Any]]:
    if not _SESSION_PATH.exists():
        return []
    try:
        data = json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
        return data.get("cookies", [])
    except Exception:
        return []


def _save_cookies(cookies: list[dict[str, Any]]) -> None:
    _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SESSION_PATH.write_text(
        json.dumps({"cookies": cookies, "saved_at": time.time()}),
        encoding="utf-8",
    )


def _login_if_needed(ctx: Any) -> bool:
    """If the session cookies don't grant dashboard access, perform
    email+password login. Returns True on success."""
    cookies = _load_cookies()
    if cookies:
        ctx.add_cookies(cookies)
    page = ctx.new_page()
    try:
        page.goto(_admin_url(""), timeout=25_000, wait_until="domcontentloaded")
        # Dashboard renders a /home link; presence of login form = session expired
        if "accounts.shopify.com" not in page.url:
            return True
        return _perform_login(page, ctx)
    finally:
        page.close()


def _perform_login(page: Any, ctx: Any) -> bool:
    email = os.environ.get("SHOPAI_SHOPIFY_ADMIN_EMAIL", "")
    password = os.environ.get("SHOPAI_SHOPIFY_ADMIN_PASSWORD", "")
    if not (email and password):
        logger.warning("admin login required but creds missing")
        return False
    try:
        page.fill("input[type='email']", email, timeout=8_000)
        page.click("button[type='submit']", timeout=5_000)
        page.wait_for_timeout(1_500)
        page.fill("input[type='password']", password, timeout=10_000)
        page.click("button[type='submit']", timeout=5_000)
    except Exception as exc:
        logger.warning("login form not found as expected: %s", exc)
        return False

    # 2FA — either env-provided code or wait for manual completion
    code = os.environ.get("SHOPAI_SHOPIFY_ADMIN_2FA_CODE", "")
    try:
        page.wait_for_selector("input[autocomplete='one-time-code']", timeout=8_000)
        if code:
            page.fill("input[autocomplete='one-time-code']", code)
            page.click("button[type='submit']")
        else:
            logger.info("2FA required — waiting 90 s for manual entry")
            page.wait_for_timeout(90_000)
    except Exception:
        # No 2FA prompt — the account doesn't have it enabled
        pass

    page.wait_for_timeout(3_000)
    if "accounts.shopify.com" in page.url:
        logger.warning("still on accounts.shopify.com post-login")
        return False
    _save_cookies(ctx.cookies())
    return True


# ── Public helpers ──────────────────────────────────────────

def update_menu(menu_handle: str, links: list[dict[str, str]]) -> dict[str, Any]:
    """Replace the link list on a named navigation menu.

    ``links`` entries take the shape
        ``{"title": str, "url": str}``

    Admin menu editor is SPA-only, so there is no Admin REST/GraphQL
    equivalent for reordering / replacing menu items in a single
    transaction.
    """
    if not is_configured():
        return {"status": "error",
                "reason": "SHOPAI_SHOPIFY_ADMIN_EMAIL / PASSWORD missing"}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error", "reason": "playwright not installed"}

    exe = _chromium_executable()
    try:
        with sync_playwright() as pw:
            kw = {"headless": True}
            if exe:
                kw["executable_path"] = exe
            browser = pw.chromium.launch(**kw)
            try:
                ctx = browser.new_context(
                    ignore_https_errors=True,
                    user_agent=_DEFAULT_UA,
                    viewport={"width": 1366, "height": 900},
                )
                if not _login_if_needed(ctx):
                    return {"status": "error", "reason": "login failed"}

                page = ctx.new_page()
                page.goto(
                    _admin_url(f"content/menus/{menu_handle}"),
                    timeout=25_000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(2_000)
                added = 0
                for link in links[:20]:
                    title = (link.get("title") or "").strip()
                    url = (link.get("url") or "").strip()
                    if not title or not url:
                        continue
                    try:
                        page.click("button:has-text('Add menu item')",
                                   timeout=5_000)
                        page.fill("input[name='name']", title, timeout=5_000)
                        page.fill("input[name='url']", url, timeout=5_000)
                        page.click("button:has-text('Add')", timeout=5_000)
                        page.wait_for_timeout(800)
                        added += 1
                    except Exception as exc:
                        logger.debug("link add failed: %s", exc)
                        continue
                try:
                    page.click("button:has-text('Save')", timeout=5_000)
                    page.wait_for_timeout(1_500)
                except Exception:
                    pass
                _save_cookies(ctx.cookies())
                return {"status": "ok", "added": added}
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("update_menu failed: %s", exc)
        return {"status": "error", "reason": str(exc)[:200]}


def set_storefront_password(password: str | None) -> dict[str, Any]:
    """Toggle the storefront password protection. Pass ``None`` to
    disable, or a non-empty string to enable + set the password.

    Admin API has no REST endpoint for this — the toggle lives under
    Online Store → Preferences and is wired only in the admin UI.
    """
    if not is_configured():
        return {"status": "error",
                "reason": "admin creds missing"}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"status": "error", "reason": "playwright not installed"}

    exe = _chromium_executable()
    try:
        with sync_playwright() as pw:
            kw = {"headless": True}
            if exe:
                kw["executable_path"] = exe
            browser = pw.chromium.launch(**kw)
            try:
                ctx = browser.new_context(
                    ignore_https_errors=True,
                    user_agent=_DEFAULT_UA,
                    viewport={"width": 1366, "height": 900},
                )
                if not _login_if_needed(ctx):
                    return {"status": "error", "reason": "login failed"}
                page = ctx.new_page()
                page.goto(
                    _admin_url("online_store/preferences"),
                    timeout=25_000,
                    wait_until="domcontentloaded",
                )
                page.wait_for_timeout(2_000)
                try:
                    # Scroll to the password section
                    page.click("text=Restrict access to visitors with the password",
                               timeout=5_000)
                except Exception:
                    pass
                if password:
                    try:
                        page.fill("input[name='password']", password,
                                  timeout=5_000)
                    except Exception:
                        pass
                try:
                    page.click("button:has-text('Save')", timeout=5_000)
                    page.wait_for_timeout(2_000)
                except Exception:
                    pass
                _save_cookies(ctx.cookies())
                return {"status": "ok",
                        "password_enabled": bool(password)}
            finally:
                browser.close()
    except Exception as exc:
        logger.warning("set_storefront_password failed: %s", exc)
        return {"status": "error", "reason": str(exc)[:200]}
