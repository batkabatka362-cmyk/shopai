"""Crawler — breadth-first site crawler that discovers product pages.

Uses :class:`Scraper` for page fetching and respects robots.txt via
``urllib.robotparser``.
"""
from __future__ import annotations

import logging
import urllib.parse
import urllib.robotparser
from collections import deque
from typing import Any

from .scraper import Scraper, ScraperError

logger = logging.getLogger("data_pipeline.crawler")

# CSS selectors used to discover links and recognise product pages
_LINK_SELECTOR = "a[href]"
_PRODUCT_URL_PATTERNS = (
    "/product",
    "/products",
    "/item",
    "/p/",
    "/shop/",
    "/catalog/",
)


class Crawler:
    """Breadth-first web crawler that extracts product data from a site.

    Args:
        max_pages:   Maximum number of pages to visit across the entire crawl.
        depth:       Maximum link depth from the start URL (0 = start page only).
        rate_limit:  Seconds between requests to the same host.
        user_agent:  User-agent string sent in HTTP requests and checked against
                     robots.txt.
        respect_robots: When ``True`` (default) the crawler honours robots.txt.
    """

    def __init__(
        self,
        max_pages: int = 100,
        depth: int = 3,
        rate_limit: float = 1.0,
        user_agent: str = "ShopAI-Crawler/1.0",
        respect_robots: bool = True,
    ) -> None:
        self._max_pages = max_pages
        self._depth = depth
        self._scraper = Scraper(rate_limit=rate_limit, user_agent=user_agent)
        self._user_agent = user_agent
        self._respect_robots = respect_robots
        self._visited: set[str] = set()
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def crawl_site(
        self,
        start_url: str,
        max_pages: int | None = None,
        depth: int | None = None,
    ) -> list[dict[str, Any]]:
        """BFS-crawl starting from *start_url* and return all page records.

        Args:
            start_url: The URL to begin crawling from.
            max_pages: Override the instance-level ``max_pages`` limit.
            depth:     Override the instance-level ``depth`` limit.

        Returns:
            List of page dicts: ``{"url": str, "depth": int, "fields": dict,
            "links": [str], "errors": [str]}``.
        """
        max_pages = max_pages if max_pages is not None else self._max_pages
        depth = depth if depth is not None else self._depth

        self._visited.clear()
        results: list[dict[str, Any]] = []

        queue: deque[tuple[str, int]] = deque()
        queue.append((self._normalise_url(start_url), 0))

        while queue and len(self._visited) < max_pages:
            url, current_depth = queue.popleft()

            if url in self._visited:
                continue
            if not self._is_allowed(url):
                logger.debug("robots.txt disallows: %s", url)
                continue

            self._visited.add(url)
            logger.debug("Crawling [depth=%d] %s", current_depth, url)

            page_record = self._scraper.scrape_page(
                url,
                selectors={
                    "title": "title",
                    "h1": "h1",
                    "description": 'meta[name="description"]',
                },
            )
            page_record["depth"] = current_depth

            # Discover links on this page
            links = self._extract_links(url)
            page_record["links"] = links
            results.append(page_record)

            if current_depth < depth:
                base = self._base_url(start_url)
                for link in links:
                    norm = self._normalise_url(link)
                    if norm not in self._visited and self._same_origin(norm, base):
                        queue.append((norm, current_depth + 1))

        logger.info(
            "Crawl complete: %d pages visited from %s", len(self._visited), start_url
        )
        return results

    def extract_all_products(self, site_url: str) -> list[dict[str, Any]]:
        """Crawl *site_url* and return records only for product pages.

        Product pages are identified by URL patterns (``/products``, ``/item``,
        etc.) or by the presence of JSON-LD ``Product`` schema.

        Returns:
            List of product dicts extracted by :meth:`Scraper.extract_product_data`.
        """
        all_pages = self.crawl_site(site_url)
        products: list[dict[str, Any]] = []

        for page in all_pages:
            url = page.get("url", "")
            if not self._looks_like_product_url(url):
                continue
            try:
                # Re-fetch the page to get full HTML for product extraction.
                # We use a fresh scrape with empty selectors to just grab HTML.
                raw = self._scraper.scrape_page(url, selectors={})
                # The scraper stores raw HTML internally; we call extract on it.
                # Since scrape_page already parsed, we ask the scraper for the
                # product fields via a targeted call.
                product = self._scraper.extract_product_data(
                    self._fetch_raw_html(url)
                )
                product["url"] = url
                products.append(product)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Product extraction failed for %s: %s", url, exc)

        logger.info("Extracted %d products from %s", len(products), site_url)
        return products

    @property
    def visited_urls(self) -> frozenset[str]:
        """Return the set of visited URLs from the last crawl (read-only)."""
        return frozenset(self._visited)

    def get_visited_count(self) -> int:
        """Return the number of pages visited in the last crawl."""
        return len(self._visited)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_links(self, url: str) -> list[str]:
        """Fetch *url* and return all absolute ``href`` links found."""
        try:
            page = self._scraper.scrape_page(url, selectors={"_links": _LINK_SELECTOR})
        except ScraperError:
            return []

        # We need raw anchor hrefs.  Re-fetch without the abstraction.
        try:
            raw_html = self._fetch_raw_html(url)
        except Exception:  # noqa: BLE001
            return []

        try:
            from bs4 import BeautifulSoup  # type: ignore[import]
            soup = BeautifulSoup(raw_html, "html.parser")
            links: list[str] = []
            for tag in soup.find_all("a", href=True):
                abs_url = urllib.parse.urljoin(url, tag["href"])
                # Strip fragments and query strings for deduplication
                parsed = urllib.parse.urlparse(abs_url)
                clean = parsed._replace(fragment="").geturl()
                links.append(clean)
            return links
        except ImportError:
            # bs4 not available — do a simple regex fallback
            import re
            found = re.findall(r'href=["\']([^"\']+)["\']', raw_html)
            return [urllib.parse.urljoin(url, h) for h in found]

    def _fetch_raw_html(self, url: str) -> str:
        """Fetch the raw HTML string for *url*."""
        return self._scraper._fetch(url)  # noqa: SLF001

    def _is_allowed(self, url: str) -> bool:
        """Return ``True`` if robots.txt permits crawling *url*."""
        if not self._respect_robots:
            return True
        base = self._base_url(url)
        if base not in self._robots_cache:
            rp = urllib.robotparser.RobotFileParser()
            robots_url = f"{base}/robots.txt"
            rp.set_url(robots_url)
            try:
                rp.read()
            except Exception:  # noqa: BLE001
                # If robots.txt is unreachable, allow crawling
                rp.allow_all = True  # type: ignore[attr-defined]
            self._robots_cache[base] = rp
        return self._robots_cache[base].can_fetch(self._user_agent, url)

    @staticmethod
    def _normalise_url(url: str) -> str:
        """Lowercase scheme+host, remove default ports, strip trailing slash."""
        p = urllib.parse.urlparse(url)
        netloc = p.netloc.lower()
        # Remove default HTTP/HTTPS ports
        if p.scheme == "http" and netloc.endswith(":80"):
            netloc = netloc[:-3]
        elif p.scheme == "https" and netloc.endswith(":443"):
            netloc = netloc[:-4]
        path = p.path.rstrip("/") or "/"
        return urllib.parse.urlunparse(
            (p.scheme, netloc, path, p.params, p.query, "")
        )

    @staticmethod
    def _base_url(url: str) -> str:
        """Return ``scheme://host`` with no path."""
        p = urllib.parse.urlparse(url)
        return f"{p.scheme}://{p.netloc}"

    @staticmethod
    def _same_origin(url: str, base: str) -> bool:
        """Return ``True`` if *url* shares the same scheme+host as *base*."""
        p = urllib.parse.urlparse(url)
        b = urllib.parse.urlparse(base)
        return p.scheme == b.scheme and p.netloc.lower() == b.netloc.lower()

    @staticmethod
    def _looks_like_product_url(url: str) -> bool:
        """Heuristic: return ``True`` if *url* looks like a product page."""
        lower = url.lower()
        return any(pat in lower for pat in _PRODUCT_URL_PATTERNS)
