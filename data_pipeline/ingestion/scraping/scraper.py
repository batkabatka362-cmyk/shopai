"""Scraper — fetches and parses web pages for product and price data.

BeautifulSoup (bs4) is used for HTML parsing when available; the class
degrades gracefully and returns empty results if the library is absent.
"""
from __future__ import annotations

import logging
import re
import time
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
        self.rate_limit = rate_limit
        self.user_agent = user_agent
        self._timeout = timeout
        self._last_request_time: dict[str, float] = {}  # host → epoch seconds

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
        result: dict[str, Any] = {"url": url, "fields": {}, "errors": []}
        try:
            html = self._fetch(url)
        except ScraperError as exc:
            result["errors"].append(str(exc))
            return result

        if not _BS_AVAILABLE:
            result["errors"].append("BeautifulSoup (bs4) not installed; cannot parse HTML")
            return result

        soup = _BS(html, "html.parser")
        for field, selector in selectors.items():
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

        soup = _BS(html, "html.parser")

        # --- JSON-LD schema ---
        json_ld = self._extract_json_ld_product(soup)
        if json_ld:
            product["title"] = json_ld.get("name", "")
            product["description"] = json_ld.get("description", "")
            product["sku"] = json_ld.get("sku", "")
            offer = json_ld.get("offers", {})
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            product["price"] = self._parse_price_float(str(offer.get("price", "")))
            product["availability"] = offer.get("availability", "").replace(
                "http://schema.org/", ""
            )
            imgs = json_ld.get("image", [])
            product["images"] = imgs if isinstance(imgs, list) else ([imgs] if imgs else [])
            return product

        # --- Open Graph fallback ---
        og_title = soup.find("meta", property="og:title")
        if og_title:
            product["title"] = og_title.get("content", "")

        og_desc = soup.find("meta", property="og:description")
        if og_desc:
            product["description"] = og_desc.get("content", "")

        og_img = soup.find("meta", property="og:image")
        if og_img:
            product["images"] = [og_img.get("content", "")]

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

        Returns:
            Raw HTML string.

        Raises:
            ScraperError: on any network or HTTP error.
        """
        host = self._extract_host(url)
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
            self._last_request_time[host] = time.monotonic()

    def _throttle(self, host: str) -> None:
        """Sleep if necessary to honour the rate limit for *host*."""
        last = self._last_request_time.get(host, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)

    @staticmethod
    def _extract_host(url: str) -> str:
        """Return the scheme+host portion of *url* for rate-limiting purposes."""
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

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
    def _parse_price_float(text: str) -> float | None:
        """Convert a price string like ``"$1,234.56"`` to ``1234.56``."""
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text.replace(",", ""))
        try:
            return float(cleaned)
        except ValueError:
            return None
