"""SerperAdapter — Serper.dev Google SERP proxy.

Serper.dev is a thin proxy that returns Google's actual SERP
results in JSON. We pick this adapter when:

  * The brain specifically wants Google's index (e.g.
    competitor SEO research, ad keyword discovery)
  * Volume matters — Serper offers 2,500 free queries/month,
    the most generous free tier among SERP-style adapters

Why not the only adapter:

  * Bound to Google's algorithmic bubble (downside for
    diverse research)
  * Free tier is monthly, easy to burn in a single competitor
    deep-dive
  * One key compromise = single point of failure (vs running
    DDGS without keys)

So Serper is registered alongside Brave + DDGS and the smart
router picks the best one for each call. Reference:
https://serper.dev/api-reference
"""
from __future__ import annotations

import json
from typing import Any

from ..base import Capability
from ..errors import AdapterError, AdapterTimeout, AdapterUnavailable
from ._base import SearchBaseAdapter, SearchHit

# Serper requires POST with JSON body, not GET — the base's
# _http_get helper does GET. We override _execute to call a
# small POST helper instead.

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False


class SerperAdapter(SearchBaseAdapter):
    name = "serper"
    base_url = "https://google.serper.dev/search"
    config_alias = "serper"
    capabilities = {Capability.WEB_SEARCH}

    # Slightly below Brave because of the Google-bubble bias,
    # but well above DDGS — when configured, Serper is a great
    # second-choice candidate.
    priority = 80
    cost_per_call = 0.0
    free_tier_daily_limit = 0
    free_tier_monthly_limit = 2_500

    # ── Vendor request (POST, not GET) ─────────────────────────
    #
    # Serper's API expects ``POST /search`` with a JSON body and
    # an ``X-API-KEY`` header. The base's ``_http_get`` does GET
    # only, so we override ``_build_request`` to return the URL
    # and headers and add a ``_http_post`` call inside ``_execute``.

    def _build_request(
        self,
        query: str,
        max_results: int,
    ) -> tuple[str, dict[str, str]]:
        # Returned for completeness — _execute below uses
        # _http_post and ignores the URL portion of this tuple.
        headers = {
            "X-API-KEY": self._api_key(),
            "Content-Type": "application/json",
        }
        return self.base_url, headers

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        # Same validation as the base, then POST instead of GET.
        from ..base import AdapterResult
        from ..errors import AdapterValidationError

        if capability != Capability.WEB_SEARCH:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        query = params.get("query") or params.get("q")
        if not isinstance(query, str) or not query.strip():
            raise AdapterValidationError(
                self.name, "'query' must be a non-empty string",
            )

        max_results = int(params.get("max_results") or self.max_results_default)
        max_results = max(1, min(max_results, 100))

        url, headers = self._build_request(query, max_results)
        body = {
            "q": query,
            "num": max_results,
        }
        raw = self._http_post(url, body, headers=headers)
        hits = self._parse_response(raw, query=query)
        hits = self._dedup_and_trim(hits, max_results)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "query": query,
                "hits": hits,
                "count": len(hits),
            },
            raw=raw,
        )

    def _http_post(
        self,
        url: str,
        body: dict[str, Any],
        headers: dict[str, str],
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            response = _requests.post(
                url, json=body, headers=headers, timeout=self.timeout,
            )
        except _requests.Timeout as exc:  # type: ignore[union-attr]
            raise AdapterTimeout(
                self.name, f"timeout after {self.timeout}s: {exc}",
            ) from exc
        except _requests.ConnectionError as exc:  # type: ignore[union-attr]
            raise AdapterUnavailable(
                self.name, f"connection error: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise AdapterError(
                self.name,
                f"http post failed: {type(exc).__name__}: {exc}",
            ) from exc

        if response.status_code >= 400:
            self._raise_for_status(
                response.status_code, getattr(response, "text", "") or "",
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc

    # ── Vendor parser ─────────────────────────────────────────

    def _parse_response(
        self,
        raw: Any,
        *,
        query: str,
    ) -> list[SearchHit]:
        if not isinstance(raw, dict):
            return []

        organic = raw.get("organic") or []
        if not isinstance(organic, list):
            return []

        now = self._now_iso()
        hits: list[SearchHit] = []
        for r in organic:
            if not isinstance(r, dict):
                continue
            url = str(r.get("link", "") or "")
            title = str(r.get("title", "") or "")
            snippet = str(r.get("snippet", "") or "")
            if not url or not title:
                continue
            hits.append(SearchHit(
                title=title,
                url=url,
                snippet=snippet,
                source=self._domain_of(url),
                retrieved_at=now,
            ))
        return hits

    @staticmethod
    def _domain_of(url: str) -> str:
        try:
            import urllib.parse
            return urllib.parse.urlparse(url).netloc
        except Exception:  # noqa: BLE001
            return ""
