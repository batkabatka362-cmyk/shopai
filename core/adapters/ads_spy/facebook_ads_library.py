"""FacebookAdsLibraryAdapter — Meta's public ad transparency feed.

The Facebook Ads Library (https://www.facebook.com/ads/library)
is Meta's public-interest transparency product. Every ad running
on Facebook / Instagram is listed there with its creative, page,
first-seen date, country targets, and (for political / issue
ads) spend ranges.

Two access paths:

  * **Public GraphQL endpoint** — used by the web UI itself.
    Returns structured JSON but is IP-rate-limited and often
    requires a session cookie. Works without a key for a few
    hundred queries per day per IP.

  * **Official Ads Library API** (requires an access token +
    ads management permission). Much higher rate limits,
    access to more fields (currency, impressions range), and
    no IP throttling. Opt-in via ``FB_ADS_LIBRARY_TOKEN``.

This adapter prefers the official API when a token is set and
falls back to the public endpoint otherwise — so operators can
start free and upgrade without code changes.

Rate-limiting: the adapter stays conservative (20 results per
query by default) to avoid tripping Meta's anti-scraping
protections. For bulk discovery, prefer Minea.

Reference: https://www.facebook.com/ads/library/api (official)
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterValidationError
from ._base import AdsSpyBaseAdapter


_PUBLIC_GRAPH_URL = "https://graph.facebook.com/v21.0/ads_archive"


class FacebookAdsLibraryAdapter(AdsSpyBaseAdapter):
    name = "fb_ads_library"
    base_url = _PUBLIC_GRAPH_URL
    config_alias = "fb_ads_library_token"

    # Lower priority than paid APIs (signal quality is lower —
    # engagement stats aren't exposed, so days_running is the
    # only strong ranking signal). Free tier still outranks
    # nothing, so it's the fallback when no paid key is set.
    priority = 60
    cost_per_call = 0.0  # free endpoint

    # The key is OPTIONAL — without it we fall back to the
    # public-mode call path. So the adapter reports "configured"
    # even when ``FB_ADS_LIBRARY_TOKEN`` is empty.
    requires_key = False

    # ── Auth ───────────────────────────────────────────────────

    def _access_token(self) -> str:
        return get_config().get(self.config_alias, "")

    def _auth_headers(self) -> dict[str, str]:
        # No Bearer header — the Meta endpoint takes the token
        # as an ``access_token`` query-string param instead.
        return {
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
        # Meta caps at 250 results per single call
        if limit > 250:
            limit = 250
        country = str(params.get("country", "US") or "US")
        ad_active = str(params.get("ad_active_status", "ACTIVE") or "ACTIVE")

        fields = (
            "id,page_name,ad_creative_link_captions,"
            "ad_creative_link_titles,ad_creative_bodies,"
            "ad_delivery_start_time,ad_delivery_stop_time,"
            "ad_snapshot_url,publisher_platforms,"
            "ad_creative_link_descriptions"
        )

        query_params: dict[str, Any] = {
            "search_terms": query,
            "ad_reached_countries": f"['{country}']",
            "limit": limit,
            "ad_active_status": ad_active,
            "ad_type": "ALL",
            "fields": fields,
        }
        token = self._access_token()
        if token:
            query_params["access_token"] = token

        raw = self._http_request("GET", self.base_url, params=query_params)
        records = [
            _map_graph_record(item)
            for item in _extract_ad_list(raw)
        ]
        return self._build_response(
            capability, records, query=query, raw=raw,
        )

    # ── Top products (proxy: broad-category search) ───────────

    def _do_top_products(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        # Meta's Ads Library has no "trending" endpoint — they
        # only let you search. We proxy by running a search for
        # the provided category (or a dropshipping-heuristic
        # default) and filtering to long-running ads which are
        # the winning-product signal.
        category = str(params.get("category", "") or "").strip()
        if not category:
            # Fall back to a permissive dropshipping default
            # so callers that forget to pass a category still
            # get a signal rather than an error.
            category = params.get("query") or "gadget"
        search_params = dict(params)
        search_params["query"] = str(category)
        search_params.setdefault("limit", 50)
        result = self._do_search(capability, search_params)
        if not result.ok:
            return result

        # Sort by days_running desc as a crude "top" proxy, then
        # trim to the requested limit.
        limit = int(params.get("limit", 50))
        ads = result.data.get("ads", [])
        ads_sorted = sorted(
            ads, key=lambda a: a.get("days_running", 0), reverse=True,
        )[:limit]
        result.data = dict(result.data)
        result.data["ads"] = ads_sorted
        result.data["total"] = len(ads_sorted)
        result.data["query"] = f"trending:{category}"
        return result

    # ── Ad details ────────────────────────────────────────────

    def _do_ad_details(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_ad_details(params)
        ad_id = str(params["ad_id"])
        if not ad_id.isdigit():
            raise AdapterValidationError(
                self.name, f"FB ad_id must be numeric (got {ad_id!r})",
            )

        fields = (
            "id,page_name,ad_creative_link_captions,"
            "ad_creative_link_titles,ad_creative_bodies,"
            "ad_delivery_start_time,ad_delivery_stop_time,"
            "ad_snapshot_url,publisher_platforms,"
            "ad_creative_link_descriptions,currency,"
            "impressions,spend"
        )

        query_params: dict[str, Any] = {
            "fields": fields,
        }
        token = self._access_token()
        if token:
            query_params["access_token"] = token

        url = f"https://graph.facebook.com/v21.0/{ad_id}"
        raw = self._http_request("GET", url, params=query_params)
        records = [_map_graph_record(raw)] if isinstance(raw, dict) else []
        return self._build_response(
            capability, records, query=f"ad_id:{ad_id}", raw=raw,
        )


def _extract_ad_list(raw: Any) -> list[dict[str, Any]]:
    """Pull the list of ad dicts from a Meta Graph response."""
    if not isinstance(raw, dict):
        return []
    data = raw.get("data")
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _first_of_list(value: Any) -> str:
    """Meta returns many creative fields as single-element lists.

    Normalise to the first scalar so downstream consumers don't
    have to special-case the shape.
    """
    if isinstance(value, list) and value:
        return str(value[0] or "")
    if isinstance(value, str):
        return value
    return ""


def _map_graph_record(row: dict[str, Any]) -> dict[str, Any]:
    """Convert a Meta Graph ad row into the normalised spy record.

    Kept at module level so it's unit-testable independently of
    the adapter (no HTTP mocks needed).
    """
    headlines = row.get("ad_creative_link_titles") or []
    bodies = row.get("ad_creative_link_descriptions") or []
    copy = row.get("ad_creative_bodies") or []

    start = str(row.get("ad_delivery_start_time", "") or "")[:10]
    stop = str(row.get("ad_delivery_stop_time", "") or "")[:10]
    # When the ad is still running, stop is empty; use today so
    # days_running reflects the live duration instead of 0.
    if start and not stop:
        stop = date.today().isoformat()

    # The public API doesn't expose creative MIME; the snapshot
    # URL is the best we can do. Callers that need the MP4 URL
    # upgrade to the official API token.
    snapshot = str(row.get("ad_snapshot_url", "") or "")

    impressions = row.get("impressions") or {}
    views = 0
    if isinstance(impressions, dict):
        # The official API returns impressions as {lower, upper};
        # the lower bound is the conservative floor.
        views = int(impressions.get("lower_bound", 0) or 0)

    return {
        "ad_id":         str(row.get("id", "") or ""),
        "source":        "fb_ads_library",
        "advertiser":    str(row.get("page_name", "") or ""),
        "product_url":   _first_of_list(row.get("ad_creative_link_captions")),
        "creative_url":  snapshot,
        "creative_type": "",
        "headline":      _first_of_list(headlines),
        "copy":          _first_of_list(copy),
        "cta":           "",
        "first_seen":    start,
        "last_seen":     stop,
        # days_running is computed in the base from first/last_seen.
        "engagement": {
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "views": views,
        },
        "country_targets": [],  # Meta scopes per-query, not per-record
        "language": "",
        "product_signals": {
            "price_estimate": 0.0,
            "store_platform": "",
            "category_hint": "",
        },
        "raw_url": snapshot,
    }
