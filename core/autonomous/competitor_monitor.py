"""Competitor price monitor.

Tracks up to N competitor product URLs in ``data/competitors.json``
(``{url: {last_price, last_title, last_checked}}``). Once per daemon
cycle (or on demand) loads each URL in headless Chromium, parses the
first price-like token and the page title, and diffs against the
last snapshot. Emits a ``category=competitor`` memory event when the
price changes by >= 3 %.

No LLM, no paid SaaS — Playwright + regex covers ~95 % of Shopify /
Amazon / AliExpress / direct-to-consumer landing pages. A tuned
selector list keeps the common cases deterministic; fallback regex
picks up everything else.

CRUD is via a single JSON file so operators can edit the tracked URL
list without a DB migration. Daemon writes back atomically.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("autonomous.competitor_monitor")


_STORE_PATH = Path("data/competitors.json")
_PRICE_RE = re.compile(r"(?:USD?\$|\$|€|£|¥)\s*([\d,]+(?:\.\d{1,2})?)")
_BARE_PRICE_RE = re.compile(r"\b(\d+(?:\.\d{2}))\b")
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

_MEANINGFUL_DELTA_PCT = 3.0


def add_url(url: str) -> bool:
    """Register a URL for monitoring. Returns True on new, False if
    already tracked. Silently rejects non-http(s) URLs."""
    if not url or not url.startswith(("http://", "https://")):
        return False
    store = _load()
    if url in store:
        return False
    store[url] = {
        "last_price": None,
        "last_title": None,
        "last_checked": 0,
        "first_seen": time.time(),
    }
    _save(store)
    return True


def remove_url(url: str) -> bool:
    store = _load()
    if url not in store:
        return False
    del store[url]
    _save(store)
    return True


def list_tracked() -> list[dict[str, Any]]:
    store = _load()
    return [{"url": url, **state} for url, state in store.items()]


def check_all(max_urls: int = 20) -> dict[str, Any]:
    """Probe every tracked URL. Returns counts + a list of observed
    price changes. Never raises — a flaky site just gets skipped."""
    store = _load()
    if not store:
        return {"checked": 0, "changes": []}

    # Only spin up Playwright if we actually have URLs to hit
    try:
        from core.adapters.browser.alibaba import _chromium_executable
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"checked": 0, "changes": [], "error": "playwright not installed"}

    exe = _chromium_executable()
    changes: list[dict[str, Any]] = []
    checked = 0

    try:
        with sync_playwright() as pw:
            launch_kwargs: dict[str, Any] = {"headless": True}
            if exe:
                launch_kwargs["executable_path"] = exe
            browser = pw.chromium.launch(**launch_kwargs)
            try:
                ctx = browser.new_context(
                    ignore_https_errors=True,
                    user_agent=_DEFAULT_UA,
                    viewport={"width": 1366, "height": 900},
                )
                for url in list(store.keys())[:max_urls]:
                    try:
                        snap = _probe(ctx, url)
                    except Exception as exc:
                        logger.debug("probe %s failed: %s", url, exc)
                        continue
                    checked += 1
                    prev = store.get(url) or {}
                    delta = _delta_pct(prev.get("last_price"), snap.get("price"))
                    store[url] = {
                        "last_price": snap.get("price"),
                        "last_title": snap.get("title"),
                        "last_checked": time.time(),
                        "first_seen": prev.get("first_seen") or time.time(),
                    }
                    if delta is not None and abs(delta) >= _MEANINGFUL_DELTA_PCT:
                        changes.append({
                            "url": url,
                            "title": snap.get("title", "")[:80],
                            "old_price": prev.get("last_price"),
                            "new_price": snap.get("price"),
                            "delta_pct": round(delta, 2),
                        })
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("competitor check failed: %s", exc)

    _save(store)
    _record_memory_events(changes)

    return {"checked": checked, "changes": changes}


def _probe(ctx: Any, url: str) -> dict[str, Any]:
    page = ctx.new_page()
    try:
        page.goto(url, timeout=20_000, wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        title = page.title() or ""
        # First pass — well-known price selectors
        price = None
        for sel in (
            "[itemprop='price']",
            "[data-price]",
            "[class*='price'] [class*='amount']",
            "[class*='ProductPrice']",
            "[class*='product-price']",
            ".price",
        ):
            try:
                text = page.locator(sel).first.inner_text(timeout=1_000)
            except Exception:
                continue
            price = _parse_price_text(text)
            if price is not None:
                break
        # Fallback — regex over visible page text (last 60 kB)
        if price is None:
            try:
                body = page.locator("body").inner_text(timeout=2_000)
                price = _parse_price_text(body[:60_000])
            except Exception as exc:
                logger.debug("competitor body scrape failed: %s", exc)
        return {"title": title, "price": price}
    finally:
        page.close()


def _parse_price_text(text: str) -> float | None:
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError as exc:
            logger.debug("price re parse failed: %s", exc)
    m = _BARE_PRICE_RE.search(text)
    if m:
        try:
            return float(m.group(1))
        except ValueError as exc:
            logger.debug("bare price parse failed: %s", exc)
    return None


def _delta_pct(old: float | None, new: float | None) -> float | None:
    if old is None or new is None or old <= 0:
        return None
    return (new - old) / old * 100.0


def _record_memory_events(changes: list[dict[str, Any]]) -> None:
    if not changes:
        return
    try:
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        for c in changes:
            mi.create(
                category="competitor",
                content=c,
                action="price_delta",
                score=3.5,
                tags=["competitor", "price_change",
                      "direction:down" if c["delta_pct"] < 0 else "direction:up"],
            )
    except Exception as exc:
        logger.debug("memory write for competitor changes failed: %s", exc)


def _load() -> dict[str, dict[str, Any]]:
    if not _STORE_PATH.exists():
        return {}
    try:
        return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(store: dict[str, dict[str, Any]]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STORE_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(store, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, _STORE_PATH)
