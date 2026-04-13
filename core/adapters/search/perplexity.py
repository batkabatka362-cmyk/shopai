"""PerplexityAdapter — Perplexity AI search/research API.

Perplexity provides AI-powered search with cited answers. Unlike
traditional search engines that return links, Perplexity returns
synthesized answers with source citations — ideal for market
research and competitive intelligence.

Capabilities:
  * WEB_SEARCH    — search with AI-summarized results
  * DEEP_RESEARCH — in-depth research with citations

Authentication: Bearer token.
Free tier: Limited requests.
Pricing: from $20/month for Pro.

Reference: https://docs.perplexity.ai/reference
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


class PerplexityAdapter(SearchBaseAdapter):
    name = "perplexity"
    base_url = "https://api.perplexity.ai"
    config_alias = "perplexity"

    capabilities = {Capability.WEB_SEARCH, Capability.DEEP_RESEARCH}
    priority = 80
    cost_per_call = 0.005  # ~$5/1000 requests
    free_tier_monthly_limit = 0

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

        # Use sonar for search, sonar-deep-research for deep
        model = params.get("model")
        if not model:
            model = (
                "sonar-deep-research"
                if capability == Capability.DEEP_RESEARCH
                else "sonar"
            )

        body = {
            "model": model,
            "messages": [
                {"role": "user", "content": query},
            ],
        }
        if params.get("system"):
            body["messages"].insert(
                0, {"role": "system", "content": params["system"]},
            )

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

        raw = self._http_post(url, body, headers)

        # Parse the response
        answer = ""
        citations = []
        choices = raw.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            answer = message.get("content", "")
        citations = raw.get("citations", [])

        # Build search hits from citations
        hits: list[SearchHit] = []
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        for i, cite in enumerate(citations):
            if isinstance(cite, str):
                hits.append({
                    "title": f"Source {i + 1}",
                    "url": cite,
                    "snippet": "",
                    "source": self.name,
                    "retrieved_at": now,
                })
            elif isinstance(cite, dict):
                hits.append({
                    "title": cite.get("title", f"Source {i + 1}"),
                    "url": cite.get("url", ""),
                    "snippet": cite.get("snippet", ""),
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
                "model": model,
            },
            raw=raw,
        )

    # ── Not used (we override _execute) but satisfy base class ─

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
                f"Perplexity returned {response.status_code}: {snippet}",
            )

        try:
            return response.json() if response.text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON: {exc}",
            ) from exc
