"""AdsSpyBaseAdapter — shared base for ad intelligence sources.

Concrete adapters (Minea, PiPiAds, BigSpy, Facebook Ads Library)
inherit this class and override only the vendor-specific bits:

  * ``base_url``                      — vendor API root
  * ``config_alias``                  — ``ENV_ALIASES`` key for
                                        the API credential (may
                                        be empty for fully-public
                                        endpoints like FB Ads
                                        Library).
  * ``_do_search`` / ``_do_top_products`` / ``_do_ad_details``
                                      — capability handlers

The base handles:

  * Capability dispatch for ``ADS_SPY_SEARCH``,
    ``ADS_SPY_TOP_PRODUCTS``, ``ADS_SPY_AD_DETAILS``
  * Required-field validation (query / product_hint)
  * HTTP execution with typed error mapping (reuses the same
    exception hierarchy that the ads / scraper adapters use so
    the router's retry logic stays uniform)
  * AdapterResult assembly with cost accounting

Why a dedicated base instead of piggy-backing on the scraper
base? Spy data is **structured** (ads with counts, dates, URLs),
not page HTML. Callers expect the normalised record shape below,
and conflating the two shapes produced fragile engine code.

Normalised ad-record shape (every adapter returns this exact
shape so the winning-product engine is vendor-agnostic):

    {
        "ad_id":         "<vendor id>",
        "source":        "minea | pipiads | bigspy | fb_ads_library",
        "advertiser":    "<page / store name>",
        "product_url":   "https://store.example.com/p/1",
        "creative_url":  "https://cdn.example.com/ad.mp4",
        "creative_type": "video" | "image" | "carousel",
        "headline":      "<ad headline>",
        "copy":          "<ad body copy>",
        "cta":           "SHOP_NOW" | "LEARN_MORE" | ...,
        "first_seen":    "2026-03-01",   # ISO date
        "last_seen":     "2026-04-10",
        "days_running":  40,              # derived; alpha signal
        "engagement": {
            "likes": 1234, "comments": 56, "shares": 78,
            "views": 123_456,
        },
        "country_targets": ["US", "CA", "AU", "UK"],
        "language":        "en",
        "product_signals": {
            "price_estimate":  29.99,
            "store_platform":  "shopify" | "woocommerce" | ...,
            "category_hint":   "home_gadget",
        },
        "raw_url": "https://vendor.example.com/ad/123",
    }

Missing fields MUST default to sensible empties (``""``, ``[]``,
``0``, ``{}``) so downstream consumers never have to null-guard.

The ``days_running`` field is computed in the base (not each
vendor) whenever ``first_seen`` and ``last_seen`` are parseable
as ISO dates — this guarantees a consistent value across sources.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
)
from .._per_store_credentials import (
    resolve_per_store as _resolve_per_store,
)
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
    AdapterRateLimited,
    AdapterTimeout,
    AdapterUnavailable,
    AdapterValidationError,
)

try:
    import requests as _requests
    _REQUESTS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

logger = get_logger("adapters.ads_spy")


# Spy APIs can be slow because they run ranking against millions
# of historical ads. Generous default — individual adapters tune
# when they know their vendor is faster.
_DEFAULT_TIMEOUT = 45.0


class AdsSpyBaseAdapter(BaseAdapter):
    """Abstract base for every ads intelligence adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key (e.g. ``"minea"``)
      * ``base_url``     — vendor API root
      * ``config_alias`` — env alias for the credential (or ``""``
                           for fully-public endpoints, in which
                           case ``requires_key`` should be
                           overridden to ``False``)

    They MAY override:

      * ``priority``       — router preference (0-100)
      * ``cost_per_call``  — average $/query
      * ``timeout``        — per-request timeout
      * ``requires_key``   — ``False`` for public endpoints
    """

    category = AdapterCategory.SCRAPER
    capabilities = {
        Capability.ADS_SPY_SEARCH,
        Capability.ADS_SPY_TOP_PRODUCTS,
        Capability.ADS_SPY_AD_DETAILS,
    }

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    priority: int = 50

    # Public endpoints (e.g. the HTML Facebook Ads Library) don't
    # need a key to function. Flip this to False in the subclass
    # when that's the case so ``is_configured()`` still returns
    # True and the router considers the adapter.
    requires_key: bool = True

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url:
            return False
        if not self.requires_key:
            return True
        if not self.config_alias:
            return False
        return bool((_resolve_per_store(self.config_alias) or get_config().get(self.config_alias)))

    def _api_key(self) -> str:
        if not self.requires_key:
            return ""
        key = (_resolve_per_store(self.config_alias) or get_config().get(self.config_alias))
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API key (set ${env or self.config_alias})",
            )
        return key

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        dispatch = {
            Capability.ADS_SPY_SEARCH: self._do_search,
            Capability.ADS_SPY_TOP_PRODUCTS: self._do_top_products,
            Capability.ADS_SPY_AD_DETAILS: self._do_ad_details,
        }
        handler = dispatch.get(capability)
        if handler is None:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        return handler(capability, params)

    # ── Vendor hooks (override in subclass) ────────────────────

    def _do_search(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_search must be implemented",
        )

    def _do_top_products(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_top_products must be implemented",
        )

    def _do_ad_details(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_ad_details must be implemented",
        )

    # ── Validation helpers ─────────────────────────────────────

    def _validate_search(self, params: dict[str, Any]) -> None:
        query = params.get("query")
        if not query or not isinstance(query, str):
            raise AdapterValidationError(
                self.name, "'query' is required for ads_spy_search",
            )
        limit = params.get("limit", 20)
        try:
            lim = int(limit)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, f"'limit' must be int (got {limit!r})",
            ) from exc
        if lim < 1 or lim > 500:
            raise AdapterValidationError(
                self.name, f"'limit' must be 1-500 (got {lim})",
            )

    def _validate_ad_details(self, params: dict[str, Any]) -> None:
        ad_id = params.get("ad_id")
        if not ad_id or not isinstance(ad_id, str):
            raise AdapterValidationError(
                self.name, "'ad_id' is required for ads_spy_ad_details",
            )

    # ── Record normalisation ───────────────────────────────────

    def _normalise_record(
        self, record: dict[str, Any], *, default_source: str = "",
    ) -> dict[str, Any]:
        """Fill missing fields and compute ``days_running``.

        Vendors only return what they know — this helper guarantees
        the downstream shape so engines never have to ``.get()``
        with a fallback.
        """
        source = str(record.get("source") or default_source or self.name)
        first_seen = str(record.get("first_seen", "") or "")
        last_seen = str(record.get("last_seen", "") or "")

        days_running = int(record.get("days_running", 0) or 0)
        if days_running == 0 and first_seen and last_seen:
            # Compute from dates when the vendor didn't precompute
            # it. Silently tolerate bad input so a single malformed
            # record never kills a batch — the field just stays 0.
            try:
                f = datetime.fromisoformat(first_seen).date()
                L = datetime.fromisoformat(last_seen).date()
                if L >= f:
                    days_running = (L - f).days
            except (ValueError, TypeError):
                days_running = 0

        engagement = record.get("engagement") or {}
        if not isinstance(engagement, dict):
            engagement = {}

        product_signals = record.get("product_signals") or {}
        if not isinstance(product_signals, dict):
            product_signals = {}

        country_targets = record.get("country_targets") or []
        if not isinstance(country_targets, (list, tuple)):
            country_targets = []

        return {
            "ad_id":          str(record.get("ad_id", "") or ""),
            "source":         source,
            "advertiser":     str(record.get("advertiser", "") or ""),
            "product_url":    str(record.get("product_url", "") or ""),
            "creative_url":   str(record.get("creative_url", "") or ""),
            "creative_type":  str(record.get("creative_type", "") or ""),
            "headline":       str(record.get("headline", "") or ""),
            "copy":           str(record.get("copy", "") or ""),
            "cta":            str(record.get("cta", "") or ""),
            "first_seen":     first_seen,
            "last_seen":      last_seen,
            "days_running":   days_running,
            "engagement": {
                "likes":    int(engagement.get("likes", 0) or 0),
                "comments": int(engagement.get("comments", 0) or 0),
                "shares":   int(engagement.get("shares", 0) or 0),
                "views":    int(engagement.get("views", 0) or 0),
            },
            "country_targets": [str(c) for c in country_targets],
            "language":        str(record.get("language", "") or ""),
            "product_signals": {
                "price_estimate":
                    float(product_signals.get("price_estimate", 0.0) or 0.0),
                "store_platform":
                    str(product_signals.get("store_platform", "") or ""),
                "category_hint":
                    str(product_signals.get("category_hint", "") or ""),
            },
            "raw_url": str(record.get("raw_url", "") or ""),
        }

    def _build_response(
        self,
        capability: Capability,
        records: list[dict[str, Any]],
        *,
        query: str = "",
        raw: Any = None,
    ) -> AdapterResult:
        normalised = [
            self._normalise_record(r, default_source=self.name)
            for r in records
            if isinstance(r, dict)
        ]
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source":    self.name,
                "query":     query,
                "ads":       normalised,
                "total":     len(normalised),
                "fetched_at": date.today().isoformat(),
            },
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token when a key exists. Override for
        vendor-specific schemes (X-API-Key, Basic auth, cookie)."""
        if not self.requires_key:
            return {
                "Accept": "application/json",
                "User-Agent": "ShopAI-AdsSpy/1.0",
            }
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Accept": "application/json",
            "User-Agent": "ShopAI-AdsSpy/1.0",
        }

    def _http_request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """W962-65: shared retry helper."""
        from core.adapters._http_retry import http_retry
        hdrs = headers or self._auth_headers()

        def _do_call():
            if method.upper() == "GET":
                return _requests.get(
                    url, headers=hdrs, params=params,
                    timeout=self.timeout,
                )
            return _requests.post(
                url, json=body, headers=hdrs, params=params,
                timeout=self.timeout,
            )

        return http_retry(
            _do_call,
            adapter_name=self.name,
            timeout=self.timeout,
        )
