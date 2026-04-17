"""MineaAdapter — Minea ads intelligence API.

Minea (https://minea.com) is the dropshipping-focused winning-
product discovery platform. It indexes ads from Meta
(Facebook/Instagram), TikTok, and Pinterest and exposes them
through a REST API that returns the ad, the advertiser, the
target product URL, and — critically — ``days_running`` (the
strongest proxy for "this is profitable enough that the
advertiser keeps paying to run it"). That signal is why Minea is
the primary paid source in the ShopAI spy stack.

Pricing: $49/mo starter at time of writing. The adapter tags
``cost_per_call`` with a rough amortised query cost so the smart
router prefers free sources when the budget is tight.

Authentication: ``Authorization: Bearer <MINEA_API_KEY>`` header.

Reference: https://minea.com/api-docs (private; endpoint paths
below reflect the public docs as of 2026-Q1 and may drift —
callers should monitor :py:class:`AdapterError` for 404/path
regressions).
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ._base import AdsSpyBaseAdapter


class MineaAdapter(AdsSpyBaseAdapter):
    name = "minea"
    base_url = "https://api.minea.com/v1"
    config_alias = "minea"

    # Highest priority among spy sources: most dropshipping-
    # relevant signals (days_running is computed per ad, country
    # targeting is complete, product_url is extracted from the
    # ad's landing page automatically).
    priority = 90
    # Rough amortised cost per query: $49/mo ÷ ~1500 queries/mo
    # = $0.033. The router uses this to prefer free sources when
    # the context's budget is tight.
    cost_per_call = 0.033

    requires_key = True

    # ── Search ─────────────────────────────────────────────────

    def _do_search(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_search(params)
        query = str(params["query"])
        limit = int(params.get("limit", 20))
        country = str(params.get("country", "") or "")
        platform = str(params.get("platform", "") or "")
        min_days = int(params.get("min_days_running", 0) or 0)

        url = f"{self.base_url}/ads/search"
        query_params: dict[str, Any] = {
            "q": query,
            "limit": limit,
        }
        if country:
            query_params["country"] = country
        if platform:
            query_params["platform"] = platform
        if min_days:
            query_params["min_days_running"] = min_days

        raw = self._http_request("GET", url, params=query_params)
        records = _extract_ad_list(raw)
        return self._build_response(
            capability, records, query=query, raw=raw,
        )

    # ── Top products ──────────────────────────────────────────

    def _do_top_products(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        limit = int(params.get("limit", 50))
        if limit < 1 or limit > 500:
            limit = 50
        country = str(params.get("country", "US") or "US")
        platform = str(params.get("platform", "") or "")
        window = str(params.get("window", "7d") or "7d")
        category = str(params.get("category", "") or "")

        url = f"{self.base_url}/ads/trending"
        query_params: dict[str, Any] = {
            "limit": limit,
            "country": country,
            "window": window,
        }
        if platform:
            query_params["platform"] = platform
        if category:
            query_params["category"] = category

        raw = self._http_request("GET", url, params=query_params)
        records = _extract_ad_list(raw)
        return self._build_response(
            capability, records, query=f"trending:{category or 'all'}", raw=raw,
        )

    # ── Ad details ────────────────────────────────────────────

    def _do_ad_details(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_ad_details(params)
        ad_id = str(params["ad_id"])
        url = f"{self.base_url}/ads/{ad_id}"
        raw = self._http_request("GET", url)

        record = raw.get("ad") if isinstance(raw, dict) else None
        records = [record] if isinstance(record, dict) else []
        return self._build_response(
            capability, records, query=f"ad_id:{ad_id}", raw=raw,
        )


def _extract_ad_list(raw: Any) -> list[dict[str, Any]]:
    """Pull the ad records from the Minea response envelope.

    Minea wraps results under either ``"ads"`` or ``"results"``
    depending on the endpoint; accept either so a schema tweak
    in future API versions doesn't silently break ranking.
    """
    if not isinstance(raw, dict):
        return []
    for key in ("ads", "results", "data", "items"):
        val = raw.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    return []
