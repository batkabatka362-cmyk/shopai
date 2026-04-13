"""Crawler — breadth-first site crawler that discovers product pages.

Uses :class:`Scraper` for page fetching and respects robots.txt via
``urllib.robotparser``.
"""
from __future__ import annotations

import logging
import threading
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
        self._max_pages = max_pages if isinstance(max_pages, int) and max_pages > 0 else 100
        self._depth = depth if isinstance(depth, int) and depth >= 0 else 3
        self._scraper = Scraper(rate_limit=rate_limit, user_agent=user_agent)
        self._user_agent = user_agent if isinstance(user_agent, str) and user_agent else "ShopAI-Crawler/1.0"
        self._respect_robots = bool(respect_robots)
        self._visited: set[str] = set()
        # Track "robots.txt for base URL" and "unreachable"
        # separately. Pre-audit the unreachable fallback
        # mutated the stdlib parser's ``allow_all`` flag
        # directly — that DID work (``allow_all`` is a real
        # if undocumented attribute) but it's fragile: future
        # stdlib refactors could rename it. Audit pass 44.
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._robots_unreachable: set[str] = set()
        # Protect the two caches from concurrent crawl_site
        # calls on the same Crawler instance.
        self._lock = threading.Lock()

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
        if not isinstance(start_url, str) or not start_url:
            return []
        max_pages = max_pages if isinstance(max_pages, int) and max_pages > 0 else self._max_pages
        depth = depth if isinstance(depth, int) and depth >= 0 else self._depth

        with self._lock:
            self._visited.clear()
        results: list[dict[str, Any]] = []

        queue: deque[tuple[str, int]] = deque()
        queue.append((self._normalise_url(start_url), 0))

        base = self._base_url(start_url)

        while queue and len(self._visited) < max_pages:
            url, current_depth = queue.popleft()

            if url in self._visited:
                continue
            if not self._is_allowed(url):
                logger.debug("robots.txt disallows: %s", url)
                continue

            self._visited.add(url)
            logger.debug("Crawling [depth=%d] %s", current_depth, url)

            # Fetch the page HTML ONCE and use it for both
            # the metadata extraction and the link discovery.
            # Pre-audit this did two separate fetches per
            # page (one via scrape_page, one via
            # _extract_links → _fetch_raw_html), wasting
            # bandwidth and slowing the crawl. Audit pass 44.
            try:
                raw_html = self._fetch_raw_html(url)
            except ScraperError as exc:
                results.append({
                    "url": url,
                    "depth": current_depth,
                    "fields": {},
                    "links": [],
                    "errors": [str(exc)],
                })
                continue

            page_record = self._parse_page_fields(url, raw_html)
            page_record["depth"] = current_depth

            # Discover links from the same HTML we already
            # fetched — no second round trip.
            links = self._parse_links(url, raw_html)
            page_record["links"] = links
            results.append(page_record)

            if current_depth < depth:
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
        etc.).

        Returns:
            List of product dicts extracted by :meth:`Scraper.extract_product_data`.
        """
        if not isinstance(site_url, str) or not site_url:
            return []

        all_pages = self.crawl_site(site_url)
        products: list[dict[str, Any]] = []

        for page in all_pages:
            url = page.get("url", "") if isinstance(page, dict) else ""
            if not url or not self._looks_like_product_url(url):
                continue
            try:
                # crawl_site already visited and fetched this
                # page; re-fetch here ONCE to get full HTML for
                # product extraction. Pre-audit did TWO extra
                # fetches per product (an empty-selector
                # scrape_page call plus _fetch_raw_html) — the
                # first result was discarded unused. Audit
                # pass 44.
                raw_html = self._fetch_raw_html(url)
                product = self._scraper.extract_product_data(raw_html)
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

    def _parse_page_fields(self, url: str, raw_html: str) -> dict[str, Any]:
        """Extract title / h1 / description from already-fetched HTML.

        Mirrors what ``Scraper.scrape_page`` would return, but
        operates on HTML we've ALREADY fetched — so the
        crawler never does two network calls per page.
        Audit pass 44.
        """
        result: dict[str, Any] = {"url": url, "fields": {}, "errors": []}
        try:
            from bs4 import BeautifulSoup  # type: ignore[import]
        except ImportError:
            result["errors"].append("BeautifulSoup (bs4) not installed")
            return result

        try:
            soup = BeautifulSoup(raw_html, "html.parser")
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"HTML parse failed: {exc}")
            return result

        try:
            title_el = soup.select_one("title")
            result["fields"]["title"] = title_el.get_text(strip=True) if title_el else None
            h1_el = soup.select_one("h1")
            result["fields"]["h1"] = h1_el.get_text(strip=True) if h1_el else None
            desc_el = soup.select_one('meta[name="description"]')
            if desc_el:
                # ``meta[name="description"]`` has its text in
                # the ``content`` attribute, not as inner text.
                content = desc_el.get("content") or desc_el.get_text(strip=True)
                result["fields"]["description"] = content
            else:
                result["fields"]["description"] = None
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"field extraction failed: {exc}")

        return result

    def _parse_links(self, url: str, raw_html: str) -> list[str]:
        """Extract absolute hrefs from already-fetched HTML.

        No network call — operates on the HTML the caller
        already has. Audit pass 44 replaces the pre-audit
        ``_extract_links`` which fetched the page twice per
        call (once via ``scrape_page`` with a dummy selector,
        then again via ``_fetch_raw_html``).
        """
        if not isinstance(raw_html, str) or not raw_html:
            return []
        try:
            from bs4 import BeautifulSoup  # type: ignore[import]
        except ImportError:
            import re
            found = re.findall(r'href=["\']([^"\']+)["\']', raw_html)
            return [urllib.parse.urljoin(url, h) for h in found]

        try:
            soup = BeautifulSoup(raw_html, "html.parser")
        except Exception:  # noqa: BLE001
            return []

        links: list[str] = []
        for tag in soup.find_all("a", href=True):
            href = tag.get("href")
            if not isinstance(href, str):
                continue
            abs_url = urllib.parse.urljoin(url, href)
            parsed = urllib.parse.urlparse(abs_url)
            # Only follow http(s) links — the scraper's
            # scheme allowlist will reject anything else, but
            # filter early to keep the queue clean.
            if parsed.scheme.lower() not in ("http", "https"):
                continue
            clean = parsed._replace(fragment="").geturl()
            links.append(clean)
        return links

    def _fetch_raw_html(self, url: str) -> str:
        """Fetch the raw HTML string for *url*."""
        return self._scraper._fetch(url)  # noqa: SLF001

    def _is_allowed(self, url: str) -> bool:
        """Return ``True`` if robots.txt permits crawling *url*."""
        if not self._respect_robots:
            return True
        base = self._base_url(url)

        with self._lock:
            cached = self._robots_cache.get(base)
            unreachable = base in self._robots_unreachable
        if unreachable:
            # Pre-audit this path mutated ``rp.allow_all =
            # True`` on the stdlib parser. That worked, but
            # it relied on an undocumented attribute. Track
            # unreachability explicitly instead so the intent
            # is obvious at the call site. Audit pass 44.
            return True
        if cached is not None:
            return cached.can_fetch(self._user_agent, url)

        rp = urllib.robotparser.RobotFileParser()
        robots_url = f"{base}/robots.txt"
        rp.set_url(robots_url)
        try:
            rp.read()
        except Exception:  # noqa: BLE001
            with self._lock:
                self._robots_unreachable.add(base)
            return True

        with self._lock:
            self._robots_cache[base] = rp
        return rp.can_fetch(self._user_agent, url)

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
