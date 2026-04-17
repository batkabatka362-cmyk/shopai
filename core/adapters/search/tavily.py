"""TavilyAdapter — Tavily AI search API.

Tavily is purpose-built for AI agents and RAG applications.
It returns clean, relevant search results optimized for LLM
consumption — no ads, no SEO spam.

Capabilities:
  * WEB_SEARCH    — fast search with relevant snippets
  * DEEP_RESEARCH — comprehensive search with full content

Authentication: API key in request body.
Free tier: 1,000 searches/month.
Pricing: from $25/month for 5,000 searches.

Reference: https://docs.tavily.com/
"""
from __future__ import annotations

import time
from typing import Any

from ..base import AdapterResult, Capability
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)
from ._base import SearchBaseAdapter, SearchHit

try:
    import requests as _requests
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]


class TavilyAdapter(SearchBaseAdapter):
    name = "tavily"
    base_url = "https://api.tavily.com"
    config_alias = "tavily"

    capabilities = {Capability.WEB_SEARCH, Capability.DEEP_RESEARCH}
    priority = 75
    cost_per_call = 0.001  # ~$1/1000 searches
    free_tier_monthly_limit = 1000

    # ── Override _execute for dual capabilities ───────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability not in (
            Capability.WEB_SEARCH, Capability.DEEP_RESEARCH,
        ):
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        query = params.get("query") or params.get("q")
        if not isinstance(query, str) or not query.strip():
            raise AdapterValidationError(
                self.name, "'query' must be a non-empty string",
            )

        max_results = int(params.get("max_results", 10))
        search_depth = params.get("search_depth")
        if not search_depth:
            search_depth = (
                "advanced"
                if capability == Capability.DEEP_RESEARCH
                else "basic"
            )

        body: dict[str, Any] = {
            "api_key": self._api_key(),
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_answer": True,
        }
        if params.get("include_raw_content"):
            body["include_raw_content"] = True
        if params.get("include_domains"):
            body["include_domains"] = params["include_domains"]
        if params.get("exclude_domains"):
            body["exclude_domains"] = params["exclude_domains"]
        if params.get("topic"):
            body["topic"] = params["topic"]

        url = f"{self.base_url}/search"
        headers = {"Content-Type": "application/json"}

        raw = self._http_post(url, body, headers)

        # Parse results
        answer = raw.get("answer", "")
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        hits: list[SearchHit] = []
        for r in raw.get("results", []):
            hits.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
                "source": self.name,
                "retrieved_at": now,
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "query": query,
                "answer": answer,
                "hits": hits,
                "count": len(hits),
                "search_depth": search_depth,
            },
            raw=raw,
        )

    # ── Not used (we override _execute) ────────────────────────

    def _build_request(
        self, query: str, max_results: int,
    ) -> tuple[str, dict[str, str]]:
        return "", {}

    def _parse_response(
        self, raw: Any, *, query: str = "",
    ) -> list[SearchHit]:
        return []

    # ── HTTP POST helper ───────────────────────────────────────

    def _http_post(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        if _requests is None:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            response = _requests.post(
                url, json=body, headers=headers, timeout=self.timeout,
            )
        except _requests.Timeout as exc:
            raise AdapterTimeout(
                self.name, f"timeout after {self.timeout}s",
            ) from exc
        except _requests.ConnectionError as exc:
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:
            raise AdapterError(
                self.name, f"HTTP POST failed: {exc}",
            ) from exc

        if response.status_code >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if response.status_code in (401, 403):
                raise AdapterAuthError(self.name, snippet)
            if response.status_code == 429:
                raise AdapterRateLimited(self.name, snippet)
            raise AdapterError(
                self.name,
                f"Tavily returned {response.status_code}: {snippet}",
            )

        try:
            return response.json() if response.text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON: {exc}",
            ) from exc
