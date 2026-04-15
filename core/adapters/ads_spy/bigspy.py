"""BigSpyAdapter — BigSpy cross-platform ad intelligence API.

BigSpy (https://bigspy.com) covers Facebook/Instagram, TikTok,
YouTube, Twitter, and Pinterest — broader than Minea (dropship
ads) or PiPiAds (TikTok). In the ShopAI spy stack it plays the
role of **cross-validator**: if the same product shows up as a
winner on Minea, PiPiAds, AND BigSpy, the conviction level
jumps dramatically.

Pricing: $99/mo Pro tier; free tier offers ~100 queries/day
which is enough for early-stage discovery.

Authentication: ``Authorization: Bearer <BIGSPY_API_KEY>``
header (standard OAuth-style token).

Reference: https://api.bigspy.com/docs (requires login;
endpoint paths below reflect the public docs as of 2026-Q1).
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ._base import AdsSpyBaseAdapter


class BigSpyAdapter(AdsSpyBaseAdapter):
    name = "bigspy"
    base_url = "https://api.bigspy.com/open/v1"
    config_alias = "bigspy"

    # Mid-priority: broader platform coverage but shallower
    # dropshipping-specific signals. Useful for cross-validation
    # rather than primary discovery.
    priority = 75
    cost_per_call = 0.066  # $99/mo / ~1500 queries

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

        url = f"{self.base_url}/ads/search"
        query_params: dict[str, Any] = {
            "keyword": query,
            "size": limit,
        }
        if country:
            query_params["country"] = country
        if platform:
            query_params["platform"] = platform

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
        window = str(params.get("window", "7d") or "7d")
        platform = str(params.get("platform", "") or "")

        url = f"{self.base_url}/ads/hot"
        query_params: dict[str, Any] = {
            "size": limit,
            "country": country,
            "period": window,
        }
        if platform:
            query_params["platform"] = platform

        raw = self._http_request("GET", url, params=query_params)
        records = _extract_ad_list(raw)
        return self._build_response(
            capability, records, query=f"hot:{platform or 'all'}", raw=raw,
        )

    # ── Ad details ────────────────────────────────────────────

    def _do_ad_details(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_ad_details(params)
        ad_id = str(params["ad_id"])
        url = f"{self.base_url}/ads/detail"
        raw = self._http_request("GET", url, params={"id": ad_id})

        record = raw.get("ad") if isinstance(raw, dict) else None
        if record is None and isinstance(raw, dict):
            record = raw.get("data")
        records = [record] if isinstance(record, dict) else []
        return self._build_response(
            capability, records, query=f"ad_id:{ad_id}", raw=raw,
        )


def _extract_ad_list(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    data = raw.get("data")
    if isinstance(data, dict):
        for key in ("list", "ads", "results", "items"):
            val = data.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
    for key in ("ads", "results", "items"):
        val = raw.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    return []
