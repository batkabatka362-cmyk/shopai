"""SourcingBaseAdapter — shared base for dropshipping suppliers.

A *sourcing* adapter wraps a supplier-side catalog + fulfillment
API. The canonical example is CJ Dropshipping but the category
is general enough to cover AutoDS, Zendrop, Spocket, Doba, and
similar services.

The four supported capabilities match the full winner→sale
lifecycle:

  1. **SOURCING_SEARCH_PRODUCTS** — keyword search across the
     supplier catalog. Used by the product_launch orchestrator
     to find a concrete SKU matching a winning product spotted
     in the ads_spy → winning_products pipeline.

  2. **SOURCING_GET_PRODUCT** — fetch a single product's full
     detail: variants, supplier cost, shipping origin, lead
     time. Needed before we can import the product into Shopify
     with correct retail prices.

  3. **SOURCING_CREATE_ORDER** — submit a fulfillment order to
     the supplier the moment a buyer checks out on our store.
     Returns the supplier's order id which we persist so later
     status polls can find it.

  4. **SOURCING_GET_ORDER_STATUS** — poll supplier order state
     and tracking. Drives Shopify fulfillment updates and the
     customer-facing "order is shipped" notification.

Every adapter returns the same normalised records so the
product_launch + fulfillment engines can orchestrate any supplier
without vendor-specific branching.

Normalised product record::

    {
        "sourcing_id":     "<supplier product id>",
        "source":          "cj_dropshipping | autods | ...",
        "title":           "",
        "description":     "",
        "category":        "",
        "cost_usd":        0.0,   # supplier cost, ex-shipping
        "suggested_price_usd": 0.0,  # supplier's recommendation
        "currency":        "USD",
        "images":          ["<url>", ...],
        "variants": [
            {
                "variant_id":  "<supplier variant id>",
                "sku":         "",
                "cost_usd":    0.0,
                "attributes":  {"color": "", "size": ""},
                "stock":       0,
            },
            ...
        ],
        "shipping_days_min": 0,
        "shipping_days_max": 0,
        "origin_country":  "CN | US | ...",
        "weight_grams":    0,
        "raw_url":         "",
    }

Normalised order record::

    {
        "order_id":        "<supplier order id>",
        "source":          "cj_dropshipping | ...",
        "status":          "pending | processing | shipped | delivered | cancelled",
        "tracking_number": "",
        "tracking_url":    "",
        "carrier":         "",
        "cost_usd":        0.0,
        "currency":        "USD",
        "items": [
            {
                "sourcing_id": "",
                "variant_id":  "",
                "quantity":    0,
                "cost_usd":    0.0,
            },
            ...
        ],
        "shipped_at":      "",    # ISO-8601
        "delivered_at":    "",
        "raw_payload":     {...},  # vendor's raw response
    }
"""
from __future__ import annotations

from typing import Any

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

logger = get_logger("adapters.sourcing")


# Supplier APIs often wait on supplier-side inventory / catalog
# queries behind the scenes. 60s matches the busiest endpoints
# observed in practice (CJ product search + variant join).
_DEFAULT_TIMEOUT = 60.0


class SourcingBaseAdapter(BaseAdapter):
    """Abstract base for every sourcing / dropshipping adapter.

    Concrete adapters MUST set:

      * ``name``         — registry key (e.g. ``"cj_dropshipping"``)
      * ``base_url``     — vendor API root
      * ``capabilities`` — the subset of sourcing capabilities this
                           adapter actually implements

    They MAY override:

      * ``priority``       — router preference (0-100)
      * ``cost_per_call``  — query cost (usually $0 — supplier
                             APIs are free; operator pays for
                             fulfilled orders, not queries)
      * ``timeout``        — per-request timeout
      * ``requires_key``   — ``False`` for public endpoints
    """

    category = AdapterCategory.SOURCING
    capabilities: set[Capability] = set()

    base_url: str = ""
    # Single-alias adapters point here. Two-credential adapters
    # (CJ uses email+password) override ``is_configured`` +
    # ``_authenticate`` to read two aliases.
    config_alias: str = ""
    timeout: float = _DEFAULT_TIMEOUT

    cost_per_call: float = 0.0
    priority: int = 50

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
        return bool(get_config().get(self.config_alias))

    def _api_key(self) -> str:
        if not self.requires_key:
            return ""
        key = get_config().get(self.config_alias)
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
        if capability not in self.capabilities:
            raise AdapterValidationError(
                self.name,
                f"{self.name} does not implement {capability.value}",
            )
        dispatch = {
            Capability.SOURCING_SEARCH_PRODUCTS: self._do_search_products,
            Capability.SOURCING_GET_PRODUCT:     self._do_get_product,
            Capability.SOURCING_CREATE_ORDER:    self._do_create_order,
            Capability.SOURCING_GET_ORDER_STATUS: self._do_get_order_status,
        }
        handler = dispatch.get(capability)
        if handler is None:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        return handler(capability, params)

    # ── Vendor hooks (override in subclass) ────────────────────

    def _do_search_products(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_search_products must be implemented",
        )

    def _do_get_product(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_get_product must be implemented",
        )

    def _do_create_order(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_create_order must be implemented",
        )

    def _do_get_order_status(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError(
            f"{type(self).__name__}._do_get_order_status must be implemented",
        )

    # ── Validation helpers ─────────────────────────────────────

    def _validate_search_products(self, params: dict[str, Any]) -> None:
        query = params.get("query")
        if not query or not isinstance(query, str):
            raise AdapterValidationError(
                self.name, "'query' is required for sourcing_search_products",
            )
        limit = params.get("limit", 20)
        try:
            lim = int(limit)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, f"'limit' must be int (got {limit!r})",
            ) from exc
        if lim < 1 or lim > 200:
            raise AdapterValidationError(
                self.name, f"'limit' must be 1-200 (got {lim})",
            )

    def _validate_get_product(self, params: dict[str, Any]) -> None:
        pid = params.get("sourcing_id") or params.get("product_id")
        if not pid or not isinstance(pid, str):
            raise AdapterValidationError(
                self.name,
                "'sourcing_id' (or 'product_id') is required for sourcing_get_product",
            )

    def _validate_create_order(self, params: dict[str, Any]) -> None:
        items = params.get("items")
        if not isinstance(items, list) or not items:
            raise AdapterValidationError(
                self.name,
                "'items' list is required for sourcing_create_order",
            )
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise AdapterValidationError(
                    self.name, f"items[{i}] must be a dict",
                )
            vid = item.get("variant_id") or item.get("sku")
            if not vid:
                raise AdapterValidationError(
                    self.name,
                    f"items[{i}] missing 'variant_id' (or 'sku')",
                )
            qty = item.get("quantity", 0)
            try:
                q = int(qty)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    f"items[{i}] 'quantity' must be int (got {qty!r})",
                ) from exc
            if q < 1:
                raise AdapterValidationError(
                    self.name,
                    f"items[{i}] 'quantity' must be >= 1 (got {q})",
                )
        shipping = params.get("shipping")
        if not isinstance(shipping, dict) or not shipping:
            raise AdapterValidationError(
                self.name,
                "'shipping' dict is required for sourcing_create_order",
            )
        for field_name in ("name", "address1", "country", "zip"):
            if not shipping.get(field_name):
                raise AdapterValidationError(
                    self.name,
                    f"shipping.{field_name} is required",
                )

    def _validate_get_order_status(self, params: dict[str, Any]) -> None:
        oid = params.get("order_id")
        if not oid or not isinstance(oid, str):
            raise AdapterValidationError(
                self.name,
                "'order_id' is required for sourcing_get_order_status",
            )

    # ── Record normalisation ───────────────────────────────────

    def _normalise_product(
        self, record: dict[str, Any], *, default_source: str = "",
    ) -> dict[str, Any]:
        """Fill every product-record field with a safe default."""
        source = str(record.get("source") or default_source or self.name)

        images = record.get("images") or []
        if not isinstance(images, list):
            images = []
        images = [str(u) for u in images if u]

        variants_raw = record.get("variants") or []
        if not isinstance(variants_raw, list):
            variants_raw = []
        variants = [
            self._normalise_variant(v) for v in variants_raw
            if isinstance(v, dict)
        ]

        try:
            cost = float(record.get("cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        try:
            retail = float(record.get("suggested_price_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            retail = 0.0
        try:
            weight = int(float(record.get("weight_grams", 0) or 0))
        except (TypeError, ValueError):
            weight = 0
        try:
            ship_min = int(record.get("shipping_days_min", 0) or 0)
        except (TypeError, ValueError):
            ship_min = 0
        try:
            ship_max = int(record.get("shipping_days_max", 0) or 0)
        except (TypeError, ValueError):
            ship_max = 0

        return {
            "sourcing_id":   str(record.get("sourcing_id", "") or ""),
            "source":        source,
            "title":         str(record.get("title", "") or ""),
            "description":   str(record.get("description", "") or ""),
            "category":      str(record.get("category", "") or ""),
            "cost_usd":      cost,
            "suggested_price_usd": retail,
            "currency":      str(record.get("currency", "USD") or "USD"),
            "images":        images,
            "variants":      variants,
            "shipping_days_min": ship_min,
            "shipping_days_max": ship_max,
            "origin_country": str(record.get("origin_country", "") or ""),
            "weight_grams":   weight,
            "raw_url":       str(record.get("raw_url", "") or ""),
        }

    def _normalise_variant(self, record: dict[str, Any]) -> dict[str, Any]:
        try:
            cost = float(record.get("cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            cost = 0.0
        try:
            stock = int(record.get("stock", 0) or 0)
        except (TypeError, ValueError):
            stock = 0
        attrs = record.get("attributes") or {}
        if not isinstance(attrs, dict):
            attrs = {}
        return {
            "variant_id": str(record.get("variant_id", "") or ""),
            "sku":        str(record.get("sku", "") or ""),
            "cost_usd":   cost,
            "attributes": attrs,
            "stock":      stock,
        }

    def _normalise_order(
        self, record: dict[str, Any], *, default_source: str = "",
    ) -> dict[str, Any]:
        source = str(record.get("source") or default_source or self.name)
        status = str(record.get("status") or "pending").lower()

        items_raw = record.get("items") or []
        if not isinstance(items_raw, list):
            items_raw = []
        items: list[dict[str, Any]] = []
        for it in items_raw:
            if not isinstance(it, dict):
                continue
            try:
                qty = int(it.get("quantity", 0) or 0)
            except (TypeError, ValueError):
                qty = 0
            try:
                cost = float(it.get("cost_usd", 0.0) or 0.0)
            except (TypeError, ValueError):
                cost = 0.0
            items.append({
                "sourcing_id": str(it.get("sourcing_id", "") or ""),
                "variant_id":  str(it.get("variant_id", "") or ""),
                "quantity":    qty,
                "cost_usd":    cost,
            })

        try:
            total = float(record.get("cost_usd", 0.0) or 0.0)
        except (TypeError, ValueError):
            total = 0.0

        raw = record.get("raw_payload")
        if not isinstance(raw, dict):
            raw = {}

        return {
            "order_id":        str(record.get("order_id", "") or ""),
            "source":          source,
            "status":          status,
            "tracking_number": str(record.get("tracking_number", "") or ""),
            "tracking_url":    str(record.get("tracking_url", "") or ""),
            "carrier":         str(record.get("carrier", "") or ""),
            "cost_usd":        total,
            "currency":        str(record.get("currency", "USD") or "USD"),
            "items":           items,
            "shipped_at":      str(record.get("shipped_at", "") or ""),
            "delivered_at":    str(record.get("delivered_at", "") or ""),
            "raw_payload":     raw,
        }

    def _build_products_response(
        self,
        capability: Capability,
        records: list[dict[str, Any]],
        *,
        query: str = "",
        raw: Any = None,
    ) -> AdapterResult:
        normalised = [
            self._normalise_product(r, default_source=self.name)
            for r in records if isinstance(r, dict)
        ]
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source":   self.name,
                "query":    query,
                "products": normalised,
                "total":    len(normalised),
            },
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    def _build_product_response(
        self,
        capability: Capability,
        record: dict[str, Any],
        *,
        raw: Any = None,
    ) -> AdapterResult:
        normalised = self._normalise_product(record, default_source=self.name)
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"source": self.name, "product": normalised},
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    def _build_order_response(
        self,
        capability: Capability,
        record: dict[str, Any],
        *,
        raw: Any = None,
    ) -> AdapterResult:
        normalised = self._normalise_order(record, default_source=self.name)
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={"source": self.name, "order": normalised},
            cost_usd=float(self.cost_per_call),
            raw=raw,
        )

    # ── HTTP ───────────────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        """Default: Bearer token when a key exists. Override for
        vendor-specific schemes (CJ uses ``CJ-Access-Token``)."""
        if not self.requires_key:
            return {
                "Accept":     "application/json",
                "User-Agent": "ShopAI-Sourcing/1.0",
            }
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Accept":        "application/json",
            "User-Agent":    "ShopAI-Sourcing/1.0",
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
