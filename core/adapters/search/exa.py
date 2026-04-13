"""ExaAdapter — Exa neural search API.

Exa (formerly Metaphor) uses neural embeddings instead of
keywords. Returns semantically relevant results — ideal for
finding similar products, related content, and competitor
pages that traditional search misses.

Capabilities:
  * WEB_SEARCH — neural/keyword search with content retrieval

Auth: Bearer token.
Free tier: 1,000 searches/month.
Pricing: from $5/1000 searches.

Reference: https://docs.exa.ai/reference
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


class ExaAdapter(SearchBaseAdapter):
    name = "exa"
    base_url = "https://api.exa.ai"
    config_alias = "exa"

    capabilities = {Capability.WEB_SEARCH}
    priority = 70
    cost_per_call = 0.005
    free_tier_monthly_limit = 1000

    # ── Override _execute for custom API ──────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.WEB_SEARCH:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        query = params.get("query") or params.get("q")
        if not isinstance(query, str) or not query.strip():
            raise AdapterValidationError(
                self.name, "'query' must be a non-empty string",
            )

        max_results = int(params.get("max_results", 10))
        search_type = params.get("type", "neural")  # neural or keyword

        url = f"{self.base_url}/search"
        headers = {
            "x-api-key": self._api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body: dict[str, Any] = {
            "query": query,
            "numResults": max_results,
            "type": search_type,
            "contents": {"text": {"maxCharacters": 1000}},
        }
        if params.get("include_domains"):
            body["includeDomains"] = params["include_domains"]
        if params.get("exclude_domains"):
            body["excludeDomains"] = params["exclude_domains"]
        if params.get("start_published_date"):
            body["startPublishedDate"] = params["start_published_date"]

        raw = self._http_post(url, body, headers)

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        hits: list[SearchHit] = []
        results = raw.get("results", []) if isinstance(raw, dict) else []
        for r in results:
            hits.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("text", "")[:500],
                "source": self.name,
                "retrieved_at": now,
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "query": query,
                "hits": hits,
                "count": len(hits),
                "search_type": search_type,
            },
            raw=raw,
        )

    # ── Not used (override _execute) ──────────────────────────

    def _build_request(
        self, query: str, max_results: int,
    ) -> tuple[str, dict[str, str]]:
        return "", {}

    def _parse_response(
        self, raw: Any, *, query: str = "",
    ) -> list[SearchHit]:
        return []

    # ── HTTP POST helper ───────────���──────────────────────────

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
                f"Exa returned {response.status_code}: {snippet}",
            )

        try:
            return response.json() if response.text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON: {exc}",
            ) from exc
