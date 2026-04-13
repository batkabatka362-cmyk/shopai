"""BraveSearchAdapter — Brave Search API.

Brave runs an independent web index (i.e. NOT a Google
re-skin like most "search APIs") and exposes it via a clean
JSON API. Two reasons we pick this as the high-quality
preferred adapter:

  * **Independent index** — when ShopAI does competitor
    research it's useful to NOT see the same algorithmic
    bubble Google would show. Brave's results are different
    and often catch things Google misses.
  * **Generous free tier** — 2,000 queries/month forever free,
    no credit card. The router treats Brave as the default
    when a key is configured.

Reference: https://brave.com/search/api/
"""
from __future__ import annotations

import urllib.parse
from typing import Any

from ..base import Capability
from ..config import get_config
from ..errors import AdapterNotConfigured
from ._base import SearchBaseAdapter, SearchHit


class BraveSearchAdapter(SearchBaseAdapter):
    name = "brave_search"
    base_url = "https://api.search.brave.com/res/v1/web/search"
    config_alias = "brave_search"
    capabilities = {Capability.WEB_SEARCH}

    # High priority — preferred when configured. Higher than
    # DDGS (50) because Brave's quality is markedly better.
    priority = 90
    cost_per_call = 0.0
    free_tier_daily_limit = 0       # daily limit not enforced
    free_tier_monthly_limit = 2_000

    # ── Vendor request ────────────────────────────────────────

    def _build_request(
        self,
        query: str,
        max_results: int,
    ) -> tuple[str, dict[str, str]]:
        params = {
            "q": query,
            "count": min(max_results, 20),  # Brave caps at 20
            "safesearch": "moderate",
            "result_filter": "web",
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self._api_key(),
        }
        return url, headers

    # ── Vendor parser ─────────────────────────────────────────

    def _parse_response(
        self,
        raw: Any,
        *,
        query: str,
    ) -> list[SearchHit]:
        if not isinstance(raw, dict):
            return []

        web = raw.get("web") or {}
        results = web.get("results") or []
        if not isinstance(results, list):
            return []

        now = self._now_iso()
        hits: list[SearchHit] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            url = str(r.get("url", "") or "")
            title = str(r.get("title", "") or "")
            description = str(r.get("description", "") or "")
            if not url or not title:
                continue
            hits.append(SearchHit(
                title=title,
                url=url,
                snippet=description,
                source=str(r.get("profile", {}).get("name", ""))
                       or self._domain_of(url),
                retrieved_at=now,
            ))
        return hits

    @staticmethod
    def _domain_of(url: str) -> str:
        try:
            return urllib.parse.urlparse(url).netloc
        except Exception:  # noqa: BLE001
            return ""
