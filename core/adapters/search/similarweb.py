"""SimilarWebAdapter — SimilarWeb digital intelligence API.

SimilarWeb provides competitor traffic data, engagement metrics,
and market share insights. Essential for competitive intelligence
in e-commerce.

Capabilities:
  * WEB_SEARCH — domain-level traffic/engagement data

Auth: API key in query parameter.
Free tier: Limited (5 results/query).
Pricing: enterprise pricing.

Reference: https://developers.similarweb.com/reference
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


class SimilarWebAdapter(SearchBaseAdapter):
    name = "similarweb"
    base_url = "https://api.similarweb.com/v1"
    config_alias = "similarweb"

    capabilities = {Capability.WEB_SEARCH}
    priority = 65
    cost_per_call = 0.01

    # ── Override _execute for domain analysis API ─────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.WEB_SEARCH:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        domain = params.get("domain") or params.get("query") or params.get("q")
        if not isinstance(domain, str) or not domain.strip():
            raise AdapterValidationError(
                self.name, "'domain' or 'query' is required",
            )

        # Clean domain (remove protocol if present)
        domain = domain.strip().replace("https://", "").replace("http://", "").split("/")[0]

        url = (
            f"{self.base_url}/website/{domain}/total-traffic-and-engagement/"
            f"visits?api_key={self._api_key()}&main_domain_only=false"
            f"&granularity=monthly"
        )

        if params.get("start_date"):
            url += f"&start_date={params['start_date']}"
        if params.get("end_date"):
            url += f"&end_date={params['end_date']}"

        raw = self._http_get(url)

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        visits = []
        if isinstance(raw, dict):
            for entry in raw.get("visits", []):
                visits.append({
                    "date": entry.get("date", ""),
                    "visits": entry.get("visits", 0),
                })

        # Build a search hit from the traffic data
        hits: list[SearchHit] = []
        total_visits = sum(v.get("visits", 0) for v in visits)
        if visits:
            hits.append({
                "title": f"Traffic data for {domain}",
                "url": f"https://{domain}",
                "snippet": f"Total visits: {total_visits:,} over {len(visits)} months",
                "source": self.name,
                "retrieved_at": now,
            })

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "domain": domain,
                "visits": visits,
                "total_visits": total_visits,
                "hits": hits,
                "count": len(hits),
            },
            raw=raw,
        )

    # ── Not used (override _execute) ────────────────���─────────

    def _build_request(
        self, query: str, max_results: int,
    ) -> tuple[str, dict[str, str]]:
        return "", {}

    def _parse_response(
        self, raw: Any, *, query: str = "",
    ) -> list[SearchHit]:
        return []

    # ── HTTP GET helper ───────────────────────────────────────

    def _http_get(self, url: str) -> Any:
        if _requests is None:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            response = _requests.get(
                url, timeout=self.timeout,
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
                self.name, f"HTTP GET failed: {exc}",
            ) from exc

        if response.status_code >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if response.status_code in (401, 403):
                raise AdapterAuthError(self.name, snippet)
            if response.status_code == 429:
                raise AdapterRateLimited(self.name, snippet)
            raise AdapterError(
                self.name,
                f"SimilarWeb returned {response.status_code}: {snippet}",
            )

        try:
            return response.json() if response.text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON: {exc}",
            ) from exc
