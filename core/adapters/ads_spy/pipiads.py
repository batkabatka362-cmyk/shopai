"""PiPiAdsAdapter — PiPiAds TikTok ad intelligence API.

PiPiAds (https://pipiads.com) specialises in TikTok Creative
Center-adjacent data: deeper engagement stats, shop links,
hashtag intelligence, and creator affinity. It complements
Minea (which covers Meta best) on the TikTok leg of the spy
stack.

Pricing: $77/mo VIP tier at time of writing. Amortised per-
query cost reflected in ``cost_per_call`` so the router still
prefers free/cheaper sources when budget is tight.

Authentication: ``X-API-Key: <PIPIADS_API_KEY>`` header (PiPiAds
uses a custom header rather than Bearer).

Reference: https://www.pipiads.com/api/docs (requires paid
login; endpoint paths below reflect the public docs as of
2026-Q1).
"""
from __future__ import annotations

from typing import Any

from ..base import AdapterResult, Capability
from ._base import AdsSpyBaseAdapter


class PiPiAdsAdapter(AdsSpyBaseAdapter):
    name = "pipiads"
    base_url = "https://api.pipiads.com/open/v1"
    config_alias = "pipiads"

    # Slightly below Minea because TikTok-only coverage limits
    # utility for a user undecided on target channel. Still
    # outranks free sources when a paid key is present.
    priority = 85
    cost_per_call = 0.050  # $77/mo / ~1500 queries

    requires_key = True

    # ── Auth ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._api_key(),
            "Accept": "application/json",
            "User-Agent": "ShopAI-AdsSpy/1.0",
        }

    # ── Search ─────────────────────────────────────────────────

    def _do_search(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_search(params)
        query = str(params["query"])
        limit = int(params.get("limit", 20))
        country = str(params.get("country", "") or "")
        min_days = int(params.get("min_days_running", 0) or 0)

        url = f"{self.base_url}/ads/search"
        body: dict[str, Any] = {
            "keyword": query,
            "page_size": limit,
        }
        if country:
            body["country"] = country
        if min_days:
            body["running_days_min"] = min_days

        raw = self._http_request("POST", url, body=body)
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
        category = str(params.get("category", "") or "")

        url = f"{self.base_url}/ads/top"
        body: dict[str, Any] = {
            "page_size": limit,
            "country": country,
            "window": window,
        }
        if category:
            body["category"] = category

        raw = self._http_request("POST", url, body=body)
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
        url = f"{self.base_url}/ads/detail"
        raw = self._http_request("GET", url, params={"ad_id": ad_id})

        record = raw.get("data") if isinstance(raw, dict) else None
        records = [record] if isinstance(record, dict) else []
        return self._build_response(
            capability, records, query=f"ad_id:{ad_id}", raw=raw,
        )


def _extract_ad_list(raw: Any) -> list[dict[str, Any]]:
    """Pull ad records from the PiPiAds response envelope.

    PiPiAds returns ``{"code": 0, "data": {"list": [...]}}`` on
    success. The ``code`` field is non-zero on soft errors; we
    treat missing/non-list ``list`` as zero results so ranking
    never crashes.
    """
    if not isinstance(raw, dict):
        return []
    data = raw.get("data")
    if isinstance(data, dict):
        items = data.get("list") or data.get("ads") or data.get("items")
        if isinstance(items, list):
            return [r for r in items if isinstance(r, dict)]
    # Some endpoints flatten the envelope
    for key in ("ads", "results", "items"):
        val = raw.get(key)
        if isinstance(val, list):
            return [r for r in val if isinstance(r, dict)]
    return []
