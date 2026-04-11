"""Scraper — fetches and parses web pages for product and price data.

BeautifulSoup (bs4) is used for HTML parsing when available; the class
degrades gracefully and returns empty results if the library is absent.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any

try:
    from bs4 import BeautifulSoup as _BS  # type: ignore[import]
    _BS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _BS = None  # type: ignore[assignment]
    _BS_AVAILABLE = False

logger = logging.getLogger("data_pipeline.scraper")

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; ShopAI/1.0; +https://shopai.io/bot)"
)

# URL schemes the scraper is allowed to fetch. Audit pass 44
# SECURITY: pre-audit ``_fetch`` passed any URL straight to
# ``urllib.request.urlopen``, which happily accepts
# ``file://`` (local file read), ``ftp://`` (FTP leak), and
# other non-HTTP schemes. A caller with partial control over
# the URL (e.g. a scraped link or a user-supplied config)
# could exfiltrate local files via ``file:///etc/passwd``.
_ALLOWED_SCHEMES = ("http", "https")


class ScraperError(Exception):
    """Raised when a page cannot be fetched or parsed."""


class Scraper:
    """Fetches web pages and extracts structured product data from HTML.

    Attributes:
        rate_limit:  Minimum seconds between successive requests to the
                     same host (default 1.0).
        user_agent:  ``User-Agent`` header sent with every request.
    """

    def __init__(
        self,
        rate_limit: float = 1.0,
        user_agent: str = _DEFAULT_USER_AGENT,
        timeout: int = 15,
    ) -> None:
        self.rate_limit = rate_limit if isinstance(rate_limit, (int, float)) and rate_limit >= 0 else 1.0
        self.user_agent = user_agent if isinstance(user_agent, str) and user_agent else _DEFAULT_USER_AGENT
        self._timeout = timeout if isinstance(timeout, int) and timeout > 0 else 15
        self._last_request_time: dict[str, float] = {}  # host → epoch seconds
        # Protect ``_last_request_time`` from concurrent
        # scrape_page calls on the same Scraper instance.
        # Audit pass 44.
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_page(self, url: str, selectors: dict[str, str]) -> dict[str, Any]:
        """Fetch *url* and extract fields described by *selectors*.

        Args:
            url:       The page URL to fetch.
            selectors: Mapping of ``field_name → CSS selector``.
                       Each selector is applied to the document and the
                       text content of the first match is stored.

        Returns:
            ``{"url": str, "fields": {field: value}, "errors": [...]}``
        """
        # Defensive coercion of public entry point. Audit pass 44.
        if not isinstance(url, str):
            url = ""
        if not isinstance(selectors, dict):
            selectors = {}

        result: dict[str, Any] = {"url": url, "fields": {}, "errors": []}
        if not url:
            result["errors"].append("empty url")
            return result

        try:
            html = self._fetch(url)
        except ScraperError as exc:
            result["errors"].append(str(exc))
            return result

        if not _BS_AVAILABLE:
            result["errors"].append("BeautifulSoup (bs4) not installed; cannot parse HTML")
            return result

        try:
            soup = _BS(html, "html.parser")
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"HTML parse failed: {exc}")
            return result

        for field, selector in selectors.items():
            if not isinstance(field, str) or not isinstance(selector, str):
                continue
            try:
                element = soup.select_one(selector)
                result["fields"][field] = element.get_text(strip=True) if element else None
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"Selector '{selector}' failed: {exc}")

        return result

    def extract_product_data(self, html: str) -> dict[str, Any]:
        """Parse *html* and extract common product fields using heuristics.

        Looks for JSON-LD ``Product`` schema first, then falls back to
        common CSS patterns (Open Graph tags, itemprop attributes).

        Returns:
            ``{"title": str, "price": float|None, "description": str,
               "images": [str], "sku": str, "availability": str}``
        """
        product: dict[str, Any] = {
            "title": "",
            "price": None,
            "description": "",
            "images": [],
            "sku": "",
            "availability": "",
        }

        if not _BS_AVAILABLE:
            logger.warning("bs4 not installed; extract_product_data returns empty record")
            return product

        if not isinstance(html, str) or not html:
            return product

        try:
            soup = _BS(html, "html.parser")
        except Exception as exc:  # noqa: BLE001
            logger.warning("extract_product_data: HTML parse failed: %s", exc)
            return product

        # --- JSON-LD schema ---
        json_ld = self._extract_json_ld_product(soup)
        if json_ld:
            product["title"] = json_ld.get("name") or ""
            product["description"] = json_ld.get("description") or ""
            product["sku"] = json_ld.get("sku") or ""
            # ``.get("offers", {})`` returns ``{}`` only when
            # the key is MISSING — present-but-None "offers"
            # (seen on malformed schemas) crashed the chained
            # ``.get()``. Same ``or {}`` pattern as passes
            # 32/36/40/41/42/43.
            offer = json_ld.get("offers") or {}
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            if not isinstance(offer, dict):
                offer = {}
            product["price"] = self._parse_price_float(str(offer.get("price") or ""))
            availability = offer.get("availability") or ""
            if not isinstance(availability, str):
                availability = ""
            product["availability"] = availability.replace("http://schema.org/", "")
            imgs = json_ld.get("image") or []
            product["images"] = imgs if isinstance(imgs, list) else ([imgs] if imgs else [])
            return product

        # --- Open Graph fallback ---
        og_title = soup.find("meta", property="og:title")
        if og_title:
            product["title"] = og_title.get("content") or ""

        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            product["description"] = og_desc.get("content") or ""

        og_img = soup.find("meta", property="og:image")
        if og_img:
            content = og_img.get("content") or ""
            product["images"] = [content] if content else []

        # --- itemprop fallback ---
        price_el = soup.find(itemprop="price")
        if price_el:
            raw_price = price_el.get("content") or price_el.get_text(strip=True)
            product["price"] = self._parse_price_float(raw_price)

        return product

    def extract_price(self, html_element: Any) -> float | None:
        """Extract a numeric price from an HTML element or string.

        Args:
            html_element: A BeautifulSoup ``Tag`` object *or* a plain string.

        Returns:
            Float price, or ``None`` if parsing fails.
        """
        if html_element is None:
            return None
        if isinstance(html_element, str):
            text = html_element
        elif _BS_AVAILABLE and hasattr(html_element, "get_text"):
            text = html_element.get_text(strip=True)
        else:
            text = str(html_element)

        return self._parse_price_float(text)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch(self, url: str) -> str:
        """Fetch *url* respecting the per-host rate limit.

        SECURITY: Only ``http://`` and ``https://`` URLs are
        allowed. Pre-audit the method passed any URL straight
        to ``urllib.request.urlopen``, which accepts
        ``file://`` (local file read) and ``ftp://`` — a
        caller with partial control over a URL could exfil
        ``file:///etc/passwd``. Audit pass 44.

        Returns:
            Raw HTML string.

        Raises:
            ScraperError: on any network or HTTP error, or when
                the URL uses a disallowed scheme.
        """
        if not isinstance(url, str) or not url:
            raise ScraperError("empty url")

        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
            raise ScraperError(
                f"scheme '{parsed.scheme}' not allowed; use http or https"
            )
        if not parsed.netloc:
            raise ScraperError("url missing host")

        host = f"{parsed.scheme}://{parsed.netloc}"
        self._throttle(host)

        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                charset = self._detect_charset(resp.headers.get_content_charset())
                return resp.read().decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            raise ScraperError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
        except Exception as exc:  # noqa: BLE001
            raise ScraperError(f"Failed to fetch {url}: {exc}") from exc
        finally:
            with self._lock:
                self._last_request_time[host] = time.monotonic()

    def _throttle(self, host: str) -> None:
        """Sleep if necessary to honour the rate limit for *host*."""
        with self._lock:
            last = self._last_request_time.get(host, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

    @staticmethod
    def _detect_charset(charset: str | None) -> str:
        return charset or "utf-8"

    @staticmethod
    def _extract_json_ld_product(soup: Any) -> dict[str, Any]:
        """Search for a JSON-LD ``Product`` block in *soup*.

        Returns the first matching dict or an empty dict.
        """
        import json

        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict) and data.get("@type") == "Product":
                return data
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and item.get("@type") == "Product":
                        return item
        return {}

    @staticmethod
    def _parse_price_float(text: Any) -> float | None:
        """Convert a price string like ``"$1,234.56"`` to ``1234.56``.

        Handles:
          * Standard:   ``"$1,234.56"`` → ``1234.56``
          * No thousands: ``"99.99"`` → ``99.99``
          * European:   ``"1.234,56"`` → ``1234.56``
          * Already numeric: ``99.99`` / ``99`` → float

        Returns ``None`` on any failure.
        """
        if text is None:
            return None
        if isinstance(text, (int, float)) and not isinstance(text, bool):
            return float(text)
        if not isinstance(text, str):
            return None
        s = text.strip()
        if not s:
            return None
        # Detect European-format "1.234,56" (dot thousands,
        # comma decimal) by looking for ``\d\.\d{3},\d{2}``.
        if re.search(r"\d\.\d{3},\d{2}", s):
            s = s.replace(".", "").replace(",", ".")
        # Strip everything but digits, dots, and minus sign.
        cleaned = re.sub(r"[^\d.\-]", "", s)
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
