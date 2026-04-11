"""ReviewsBaseAdapter — shared HTTP base for product-review
vendors.

Concrete adapters (Judge.me today; Yotpo, Loox, Stamped,
Okendo later) inherit this class and override only the
vendor-specific bits:

  * ``base_url``                  — vendor API root
  * ``config_alias``              — ``ENV_ALIASES`` key for the
                                    API credential
  * ``_fetch_url``                — endpoint that returns the
                                    reviews list
  * ``_auth_params``              — vendor-specific query params
                                    for authentication (Judge.me
                                    puts the token in the URL)
  * ``_auth_headers``             — vendor-specific header auth
                                    (overridable; defaults empty
                                    for query-token vendors)
  * ``_build_fetch_params``       — normalised params → vendor
                                    query string
  * ``_parse_fetch_response``     — vendor response → normalised
                                    result dict

The base handles:

  * Capability dispatch for ``Capability.PRODUCT_REVIEWS_FETCH``
  * Required-field validation (``shop_domain``; optional
    ``product_id`` / ``product_handle`` / ``per_page``)
  * Pagination bounds (per_page 1-100, page >= 1)
  * HTTP GET execution with typed error mapping
  * AdapterResult assembly; reviews are flat cost (most vendors
    charge per install/month rather than per API call)

Normalised request shape (vendor-agnostic):

    {
        "shop_domain":    "demo.myshopify.com",  # required
        "product_id":     123456,                 # optional
        "product_handle": "hero-widget",          # optional
        "per_page":       10,                     # optional (1-100)
        "page":           1,                      # optional (>=1)
        "rating_min":     4,                      # optional (1-5)
        "verified_only":  True,                   # optional
    }

Normalised response shape:

    {
        "reviews": [
            {
                "id":            "12345",
                "rating":        5,
                "title":         "Love it",
                "body":          "Exceeded expectations.",
                "reviewer_name": "Jane D.",
                "verified":      True,
                "created_at":    "2025-01-04T12:34:56Z",
                "product_id":    "gid://shopify/Product/123",
            },
            ...
        ],
        "page":        1,
        "per_page":    10,
        "count":       10,         # reviews returned this page
    }

Scope note: Wave 1 covers *fetching* reviews only. Posting,
replying, moderation, and syndication across marketplaces are
out of scope.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from utils.logger import get_logger

from ..base import (
    AdapterCategory,
    AdapterResult,
    BaseAdapter,
    Capability,
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

logger = get_logger("adapters.reviews")


_DEFAULT_TIMEOUT = 30.0
_MAX_PER_PAGE = 100


class ReviewsBaseAdapter(BaseAdapter):
    """Abstract base for every product-reviews adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key (e.g. ``"judgeme"``)
      * ``base_url``     — vendor API root
      * ``config_alias`` — env alias for the API token

    They MAY override:

      * ``priority``      — router preference (0-100)
      * ``cost_per_call`` — flat $/fetch (most review vendors
                            charge monthly subscriptions rather
                            than per API call, so 0.0 is honest)
      * ``timeout``       — per-request timeout in seconds
    """

    category = AdapterCategory.SHOPIFY_APP
    capabilities = {Capability.PRODUCT_REVIEWS_FETCH}

    base_url: str = ""
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    priority: int = 50

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        if not _REQUESTS_AVAILABLE:
            return False
        if not self.base_url or not self.config_alias:
            return False
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        key = get_config().get(self.config_alias)
        if not key:
            env = get_config().env_var_for(self.config_alias)
            raise AdapterNotConfigured(
                self.name,
                f"missing API token (set ${env or self.config_alias})",
            )
        return key

    # ── Cost estimation ────────────────────────────────────────

    def estimate_cost(
        self, capability: Capability, params: dict[str, Any],
    ) -> float:
        return float(self.cost_per_call)

    # ── Capability dispatch ────────────────────────────────────

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> AdapterResult:
        if capability != Capability.PRODUCT_REVIEWS_FETCH:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        self._validate_fetch(params)
        url = self._fetch_url()
        query = self._build_fetch_params(params)

        # Merge vendor auth params (e.g. api_token=) with the
        # caller's query so subclasses don't have to think about
        # auth when building the rest of the URL.
        auth = self._auth_params()
        if auth:
            query = [*auth, *query] if isinstance(query, list) else {
                **auth, **query,
            }

        full_url = self._append_query(url, query)
        raw = self._http_get(full_url, headers=self._auth_headers())
        normalised = self._parse_fetch_response(raw, params)

        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data=normalised,
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    # ── Validation ─────────────────────────────────────────────

    def _validate_fetch(self, params: dict[str, Any]) -> None:
        shop_domain = params.get("shop_domain")
        if not shop_domain or not isinstance(shop_domain, str):
            raise AdapterValidationError(
                self.name,
                "'shop_domain' is required (e.g. 'demo.myshopify.com')",
            )
        if "." not in shop_domain:
            raise AdapterValidationError(
                self.name,
                f"'shop_domain' must be a fully-qualified host, "
                f"got {shop_domain!r}",
            )

        per_page = params.get("per_page")
        if per_page is not None:
            try:
                pp = int(per_page)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"'per_page' must be an integer (got {per_page!r})",
                ) from exc
            if pp < 1 or pp > _MAX_PER_PAGE:
                raise AdapterValidationError(
                    self.name,
                    f"'per_page' must be between 1 and {_MAX_PER_PAGE} "
                    f"(got {pp})",
                )

        page = params.get("page")
        if page is not None:
            try:
                pg = int(page)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"'page' must be an integer (got {page!r})",
                ) from exc
            if pg < 1:
                raise AdapterValidationError(
                    self.name, f"'page' must be >= 1 (got {pg})",
                )

        rating_min = params.get("rating_min")
        if rating_min is not None:
            try:
                r = int(rating_min)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"'rating_min' must be 1-5 (got {rating_min!r})",
                ) from exc
            if r < 1 or r > 5:
                raise AdapterValidationError(
                    self.name,
                    f"'rating_min' must be between 1 and 5 (got {r})",
                )

    # ── Vendor-specific hooks (override in subclasses) ────────

    def _fetch_url(self) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._fetch_url must be implemented",
        )

    def _auth_params(self) -> list[tuple[str, str]]:
        """Vendors that authenticate via a query parameter
        (Judge.me) return ``[("api_token", ...)]`` here. Vendors
        that use a header leave this empty and override
        ``_auth_headers`` instead."""
        return []

    def _auth_headers(self) -> dict[str, str]:
        """Default: JSON-friendly Accept header, no auth. Vendors
        that use a bearer token or similar override this."""
        return {"Accept": "application/json"}

    def _build_fetch_params(
        self, params: dict[str, Any],
    ) -> list[tuple[str, str]]:
        raise NotImplementedError(
            f"{type(self).__name__}._build_fetch_params must be implemented",
        )

    def _parse_fetch_response(
        self, raw: Any, params: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError(
            f"{type(self).__name__}._parse_fetch_response must be implemented",
        )

    # ── HTTP ───────────────────────────────────────────────────

    @staticmethod
    def _append_query(url: str, params: Any) -> str:
        """Append a query string to *url*.

        Accepts either a list of ``(key, value)`` tuples (to
        preserve key order / duplicates) or a plain dict.
        Empty / None values are dropped so the URL doesn't
        carry dangling ``?foo=`` placeholders.
        """
        if isinstance(params, dict):
            items = list(params.items())
        else:
            items = list(params or [])
        items = [(k, str(v)) for k, v in items if v not in (None, "")]
        if not items:
            return url
        sep = "&" if "?" in url else "?"
        return url + sep + urlencode(items, doseq=True)

    def _http_get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if not _REQUESTS_AVAILABLE:
            raise AdapterUnavailable(
                self.name, "'requests' library not installed",
            )
        try:
            response = _requests.get(
                url, headers=headers or {}, timeout=self.timeout,
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
                f"http get failed: {type(exc).__name__}: {exc}",
            ) from exc

        status = getattr(response, "status_code", 0)
        if status >= 400:
            snippet = (getattr(response, "text", "") or "")[:200]
            if status in (401, 403):
                raise AdapterAuthError(
                    self.name,
                    f"vendor rejected credentials ({status}): {snippet}",
                )
            if status == 429:
                raise AdapterRateLimited(
                    self.name, f"rate limit (429): {snippet}",
                )
            if 500 <= status < 600:
                raise AdapterUnavailable(
                    self.name,
                    f"vendor 5xx ({status}): {snippet}",
                )
            raise AdapterError(
                self.name,
                f"vendor returned {status}: {snippet}",
            )

        try:
            text = getattr(response, "text", "") or ""
            return response.json() if text else {}
        except ValueError as exc:
            raise AdapterError(
                self.name, f"invalid JSON response: {exc}",
            ) from exc
