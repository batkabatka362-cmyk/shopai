"""DDGSAdapter — DuckDuckGo HTML search, no API key required.

Why this is the default search adapter:

  * **No API key** — works the moment ShopAI starts up, no
    operator setup required. Same role Ollama plays for LLMs.
  * **No tracking** — DuckDuckGo doesn't store the operator's
    queries, useful when the brain is researching competitors
    or testing risky search terms.
  * **Free, unlimited** — no quota, just a soft rate limit if
    you slam them with hundreds of queries per second.

How it works:

  DuckDuckGo doesn't expose a public JSON search API for web
  results (the ``api.duckduckgo.com`` "instant answer" endpoint
  only returns Wikipedia-style facts, not actual SERP results).
  We hit the HTML endpoint at ``html.duckduckgo.com/html`` with
  a normal browser User-Agent and parse the result links with
  a small set of regex patterns.

  This is intentionally brittle. If DuckDuckGo changes their
  HTML structure the adapter will start returning empty
  results — at which point the smart router will fall back to
  Brave or Serper. The brittleness is the price for "no API
  key required".

Trade-offs vs Brave/Serper:

  * Quality: lower (DuckDuckGo's index is independent but
    smaller than Google's)
  * Latency: higher (HTML scrape vs JSON API)
  * Reliability: lower (one HTML change can break parsing)
  * Cost: $0 forever
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from utils.logger import get_logger

from ..base import Capability
from ._base import SearchBaseAdapter, SearchHit

logger = get_logger("adapters.search.ddgs")


class DDGSAdapter(SearchBaseAdapter):
    name = "ddgs"
    base_url = "https://html.duckduckgo.com/html/"
    config_alias = ""  # no API key
    capabilities = {Capability.WEB_SEARCH}

    # Default priority: lower than Brave/Serper because the
    # quality is lower, but it's the only adapter that works
    # without operator setup, so the router will pick it
    # whenever the higher-priority cloud adapters are
    # un-configured.
    priority = 50
    cost_per_call = 0.0
    free_tier_daily_limit = 0  # unlimited (no quota)

    # ── Vendor request ────────────────────────────────────────

    def _build_request(
        self,
        query: str,
        max_results: int,
    ) -> tuple[str, dict[str, str]]:
        url = (
            f"{self.base_url}?q={urllib.parse.quote_plus(query)}"
        )
        headers = {
            # Browser-ish User-Agent. DDG returns a different
            # (no-results) page if the UA looks like requests/2.x.
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) "
                "Gecko/20100101 Firefox/120.0"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.5",
        }
        return url, headers

    # ── Vendor parser ─────────────────────────────────────────

    # Crude but stable: a result block is a div.result__body
    # with a result__a anchor and a result__snippet div. We use
    # one regex per field rather than dragging in BeautifulSoup
    # so the adapter has zero extra dependencies.
    _RESULT_BLOCK_RE = re.compile(
        r'<div\s+class="result__body[^"]*"[^>]*>(.+?)</div>\s*</div>\s*</div>',
        re.DOTALL,
    )
    _TITLE_LINK_RE = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.+?)</a>',
        re.DOTALL,
    )
    _SNIPPET_RE = re.compile(
        r'<a[^>]+class="result__snippet"[^>]*>(.+?)</a>',
        re.DOTALL,
    )
    _TAG_STRIP_RE = re.compile(r"<[^>]+>")
    _WHITESPACE_RE = re.compile(r"\s+")

    def _parse_response(
        self,
        raw: Any,
        *,
        query: str,
    ) -> list[SearchHit]:
        if not isinstance(raw, str):
            return []

        hits: list[SearchHit] = []
        now = self._now_iso()

        for block in self._RESULT_BLOCK_RE.finditer(raw):
            block_html = block.group(1)

            link_match = self._TITLE_LINK_RE.search(block_html)
            if not link_match:
                continue
            url = self._unwrap_ddg_redirect(link_match.group(1))
            title = self._strip_tags(link_match.group(2))
            if not url or not title:
                continue

            snippet_match = self._SNIPPET_RE.search(block_html)
            snippet = (
                self._strip_tags(snippet_match.group(1))
                if snippet_match
                else ""
            )

            source = self._domain_of(url)

            hits.append(SearchHit(
                title=title,
                url=url,
                snippet=snippet,
                source=source,
                retrieved_at=now,
            ))

        return hits

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _unwrap_ddg_redirect(url: str) -> str:
        """DDG wraps every result link in their own
        ``//duckduckgo.com/l/?uddg=<encoded>`` redirect. Unwrap
        it so the caller gets the real destination URL.
        """
        if not url:
            return ""
        if url.startswith("//"):
            url = "https:" + url
        if "duckduckgo.com/l/" in url:
            try:
                qs = urllib.parse.urlparse(url).query
                params = urllib.parse.parse_qs(qs)
                target = params.get("uddg", [""])[0]
                if target:
                    return urllib.parse.unquote(target)
            except Exception as exc:  # noqa: BLE001
                logger.debug("DuckDuckGo redirect URL parse failed: %s", exc)
        return url

    @classmethod
    def _strip_tags(cls, text: str) -> str:
        """Remove HTML tags + collapse whitespace from a result
        title or snippet."""
        if not text:
            return ""
        cleaned = cls._TAG_STRIP_RE.sub(" ", text)
        # Decode the most common HTML entities so the brain sees
        # readable text instead of "&amp;" everywhere.
        try:
            import html
            cleaned = html.unescape(cleaned)
        except Exception as exc:  # noqa: BLE001
            logger.debug("HTML entity unescape failed: %s", exc)
        return cls._WHITESPACE_RE.sub(" ", cleaned).strip()

    @staticmethod
    def _domain_of(url: str) -> str:
        try:
            return urllib.parse.urlparse(url).netloc
        except Exception:  # noqa: BLE001
            return ""
