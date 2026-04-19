"""Alibaba product-page scraper.

Alibaba has no public API for product detail, so we use a headless
Chromium (via Playwright) to render the page and extract:

    title         — product title
    price_usd     — lowest variant price in USD
    supplier_url  — canonical URL the scraper landed on
    gallery_urls  — up to 8 product image URLs
    attributes    — color / material / size etc. if the page exposes them
    raw_html      — first 50 kB, stored for offline debugging

The scraper is defensive: missing selectors just produce empty strings
so ``SourceStep`` can still decide whether the extraction is good
enough to proceed (it treats "no title" as a StepSkip, for example).

Module reads ``PLAYWRIGHT_BROWSERS_PATH`` /
``PLAYWRIGHT_CHROMIUM_EXECUTABLE`` from env so operators running in a
sandbox with a pre-installed Chromium don't need to re-download it.
"""
from __future__ import annotations

import os
import re
from typing import Any

from utils.logger import get_logger


logger = get_logger("adapters.browser.alibaba")


_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# CSS selectors that match the Alibaba product-detail layout as of 2025.
# Listed in priority order — the first non-empty match wins.
_TITLE_SELECTORS = (
    "h1.module-pdp-title",
    "h1.product-title-text",
    "h1[data-spm='d_title']",
    "h1",
)

_PRICE_SELECTORS = (
    "[class*='price'] [class*='range']",
    "[class*='product-price']",
    "span.price",
    "div.price",
)

_GALLERY_SELECTORS = (
    "ul.main-image-list img",
    "div[class*='gallery'] img",
    "div.module-pdp-mainimage img",
)


def is_configured() -> bool:
    """Playwright + Chromium available?

    We accept any of:
      * ``$PLAYWRIGHT_CHROMIUM_EXECUTABLE`` points at a working binary
      * ``$PLAYWRIGHT_BROWSERS_PATH`` contains the bundled build
      * system ``google-chrome`` / ``chromium`` on PATH
    """
    if _chromium_executable():
        return True
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _chromium_executable() -> str | None:
    # Explicit override
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "").strip()
    if exe and os.path.isfile(exe):
        return exe
    # Pre-installed bundle next to /opt/pw-browsers/chromium-*/chrome-linux/chrome
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    if os.path.isdir(base):
        for entry in sorted(os.listdir(base)):
            if entry.startswith("chromium-"):
                candidate = os.path.join(base, entry, "chrome-linux", "chrome")
                if os.path.isfile(candidate):
                    return candidate
    # System chromium
    for name in ("/usr/bin/chromium", "/usr/bin/google-chrome"):
        if os.path.isfile(name):
            return name
    return None


def scrape(url: str, timeout_ms: int = 25_000) -> dict[str, Any]:
    """Load *url* in a headless Chromium and extract the product
    contract expected by ``workflows.launch.steps.source``.

    Returns ``{}`` on failure (log warning) — caller decides whether
    to StepSkip or StepFailure.
    """
    if not url or not url.startswith(("http://", "https://")):
        return {}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("playwright not installed")
        return {}

    exe = _chromium_executable()
    result: dict[str, Any] = {}
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
                page = ctx.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                # Some Alibaba routes lazy-load the gallery; give the
                # images a beat to mount before we query them.
                page.wait_for_timeout(1_500)

                result["title"] = _first_match_text(page, _TITLE_SELECTORS)
                result["price_usd"] = _parse_price(
                    _first_match_text(page, _PRICE_SELECTORS)
                )
                result["gallery_urls"] = _collect_images(page)
                result["attributes"] = _collect_attributes(page)
                result["supplier_url"] = page.url
                try:
                    html = page.content()
                    result["raw_html"] = html[:50_000]
                except Exception:
                    pass
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("alibaba scrape failed: %s", exc)
        return {}

    return result


def _first_match_text(page: Any, selectors: tuple[str, ...]) -> str:
    for sel in selectors:
        try:
            text = page.locator(sel).first.inner_text(timeout=1_500)
        except Exception:
            continue
        text = (text or "").strip()
        if text:
            return text
    return ""


def _parse_price(raw: str) -> float:
    if not raw:
        return 0.0
    # Alibaba prices come in formats like "US$4.50-6.20" or "$ 12.99"
    numbers = re.findall(r"\d+(?:\.\d{1,2})?", raw.replace(",", ""))
    if not numbers:
        return 0.0
    try:
        return float(numbers[0])
    except ValueError:
        return 0.0


def _collect_images(page: Any, max_images: int = 8) -> list[str]:
    urls: list[str] = []
    for sel in _GALLERY_SELECTORS:
        try:
            count = page.locator(sel).count()
        except Exception:
            continue
        if not count:
            continue
        for i in range(min(count, max_images)):
            try:
                src = page.locator(sel).nth(i).get_attribute("src")
            except Exception:
                src = None
            if src and src.startswith(("http://", "https://", "//")) and src not in urls:
                urls.append(src if not src.startswith("//") else f"https:{src}")
            if len(urls) >= max_images:
                break
        if urls:
            break
    return urls


def _collect_attributes(page: Any) -> dict[str, str]:
    attrs: dict[str, str] = {}
    selectors = (
        "div[class*='attribute'] div[class*='row']",
        "table.attribute-list tr",
        "ul.product-props li",
    )
    for sel in selectors:
        try:
            count = page.locator(sel).count()
        except Exception:
            continue
        if not count:
            continue
        for i in range(min(count, 20)):
            try:
                text = page.locator(sel).nth(i).inner_text(timeout=500)
            except Exception:
                continue
            text = (text or "").strip()
            if ":" in text:
                key, val = text.split(":", 1)
            elif "\n" in text:
                key, val = text.split("\n", 1)
            else:
                continue
            key = key.strip().lower().replace(" ", "_")[:32]
            val = val.strip()[:120]
            if key and val and key not in attrs:
                attrs[key] = val
        if attrs:
            break
    return attrs
