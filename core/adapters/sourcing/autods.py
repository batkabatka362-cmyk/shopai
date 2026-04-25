"""AutoDSAdapter — dropshipping supplier + US/EU warehouse routing.

AutoDS (https://app.autods.com) is a paid dropshipping service
($9.90-$62.90/mo depending on SKU count). The free tier doesn't
include API access — paid plans do. For Deguar-scale operators
its main wins over CJ are:

  * US warehouse option (``shipping_source=us_warehouse``) —
    2-5 day delivery to US buyers vs 7-14 from CN, ~20 % CVR
    uplift on impulse-price buckets.
  * Marketplaces broader than CJ — AliExpress, Amazon, Walmart,
    CJ Dropshipping itself, BangGood, Banggood, DSers. Same
    AutoDS account can source from any.
  * Auto-pricing rules — set desired margin %, AutoDS keeps the
    Shopify price in sync with supplier cost moves.

We use only the sourcing + order surface (search / get / create
/ status). Auto-pricing + optimisation live inside AutoDS's UI
and don't expose a useful API.

Authentication: single ``Bearer <api_key>`` header.
AUTODS_API_KEY from the account's "API Keys" page.

Endpoints used:

  * ``GET  /v1/products/search``       — keyword + supplier
                                         filter search
  * ``GET  /v1/products/{id}``         — product detail incl.
                                         variants + pricing
  * ``POST /v1/orders``                — create order with
                                         buyer shipping info
  * ``GET  /v1/orders/{id}``           — order tracking + state

AutoDS's envelope is plain JSON — the top-level payload IS the
data (no ``result`` / ``code`` wrapper like CJ). Errors return
a 4xx HTTP status with ``{"error": "...", "code": "..."}``
body.

Rate limit: ~120 req/min per account on standard plans.
``SourcingBaseAdapter`` already raises ``AdapterRateLimited``
on HTTP 429 so callers get typed backoff signal.

Priority=80 (below CJ's 90) — when both are configured, CJ
wins the router pick. Owner can flip via the adapter's config.
"""
from __future__ import annotations

from typing import Any

from utils.logger import get_logger

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import AdapterError, AdapterNotConfigured
from ._base import SourcingBaseAdapter


logger = get_logger("adapters.sourcing.autods")


class AutoDSAdapter(SourcingBaseAdapter):
    """AutoDS sourcing + fulfillment adapter.

    Symmetric with ``CJDropshippingAdapter`` — implements the
    same four ``SOURCING_*`` capabilities against AutoDS's API
    and normalises responses via the shared base class.
    """

    name = "autods"
    base_url = "https://app.autods.com/api/v1"

    # Single-credential adapter — Bearer token in
    # ``Authorization`` header. ``config_alias`` points at the
    # resolver key; get_config maps it to env AUTODS_API_KEY.
    config_alias = "autods"

    capabilities = {
        Capability.SOURCING_SEARCH_PRODUCTS,
        Capability.SOURCING_GET_PRODUCT,
        Capability.SOURCING_CREATE_ORDER,
        Capability.SOURCING_GET_ORDER_STATUS,
        Capability.SOURCING_CANCEL_ORDER,
        Capability.SOURCING_LIST_ORDERS,
        Capability.SOURCING_GET_VARIANT_STOCK,
        # AutoDS doesn't expose a freight-rate endpoint —
        # only aggregate shipping_days ranges on products.
        # Leave SOURCING_GET_SHIPPING_METHODS off.
    }

    # AutoDS is the fallback supplier — CJ (priority=90) wins
    # when both are configured. Owner can flip by setting
    # ``autods_priority=95`` override env.
    priority = 80
    cost_per_call = 0.0  # catalog queries are free
    requires_key = True
    # AutoDS's search endpoint occasionally lags 3-5s on first
    # hit of the day (cold CDN); bump default 10s → 20s.
    timeout: float = 20.0

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        """Fully override ``SourcingBaseAdapter.is_configured``
        because the base gates on ``_REQUESTS_AVAILABLE`` —
        useful for live use but blocks mock-HTTP tests (where
        requests isn't imported at all). We still require the
        20-char token minimum so a truncated / placeholder
        value doesn't get mistaken for a real key."""
        if not self.base_url:
            return False
        key = get_config().get(self.config_alias) or ""
        return bool(key and len(key) >= 20)

    # ── HTTP envelope + error unwrapping ──────────────────────

    def _autods_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Hit an AutoDS endpoint + unwrap the envelope.

        AutoDS returns plain JSON — either the result directly
        (GET /products/{id}) or a ``{"results": [...],
        "total": N}`` wrapper (search). Errors come back as
        4xx with ``{"error": "...", "code": "..."}``; those
        are already surfaced as ``AdapterAuthError`` /
        ``AdapterRateLimited`` / ``AdapterError`` by the base
        HTTP layer — here we just defend against malformed
        JSON.
        """
        url = f"{self.base_url}{path}"
        raw = self._http_request(
            method, url, body=body, params=params,
        )
        if raw is None:
            return {}
        if not isinstance(raw, (dict, list)):
            raise AdapterError(
                self.name,
                "AutoDS returned non-object: "
                f"{type(raw).__name__}",
            )
        if isinstance(raw, list):
            # Some endpoints return bare lists; wrap so callers
            # use uniform dict access.
            return {"list": raw}
        # Some AutoDS responses include {"error": "..."} even
        # at HTTP 200 (plan quota exceeded, etc). Surface as
        # typed error.
        err = raw.get("error")
        if err and not raw.get("id") and not raw.get("results"):
            raise AdapterError(
                self.name,
                f"AutoDS logical failure: {err}",
            )
        return raw

    # ── Capability implementations ─────────────────────────────

    def _do_search_products(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_search_products(params)
        query = str(params["query"])
        limit = int(params.get("limit", 20))
        page = int(params.get("page", 1) or 1)
        supplier = str(params.get("supplier") or "").strip()

        query_params: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "page": page,
        }
        # Supplier filter is optional — when present, restricts
        # search to e.g. "aliexpress" or "us_warehouse". Empty
        # string means "all AutoDS sources".
        if supplier:
            query_params["supplier"] = supplier

        data = self._autods_request(
            "GET", "/products/search", params=query_params,
        )
        raw_records = _extract_autods_search(data)
        # Each raw record uses AutoDS's field names ("id",
        # "cost", ...); normalise to the canonical keys
        # (``sourcing_id``, ``cost_usd``, ...) that
        # ``_normalise_product`` expects before the base
        # response builder touches them.
        records = [
            _extract_autods_product(r) for r in raw_records
        ]
        return self._build_products_response(
            capability, records,
            query=query, raw=data,
        )

    def _do_get_product(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_get_product(params)
        pid = str(
            params.get("sourcing_id")
            or params.get("product_id"),
        )
        data = self._autods_request(
            "GET", f"/products/{pid}",
        )
        record = _extract_autods_product(data)
        return self._build_product_response(
            capability, record, raw=data,
        )

    def _do_create_order(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_create_order(params)
        body = _build_autods_order_body(params)
        data = self._autods_request(
            "POST", "/orders", body=body,
        )
        record = _extract_autods_order_ack(data, params)
        return self._build_order_response(
            capability, record, raw=data,
        )

    def _do_get_order_status(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_get_order_status(params)
        oid = str(params["order_id"])
        data = self._autods_request(
            "GET", f"/orders/{oid}",
        )
        record = _extract_autods_order_status(data, oid)
        return self._build_order_response(
            capability, record, raw=data,
        )

    # ── Wave 5 extensions ──────────────────────────────────

    def _do_cancel_order(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Cancel an AutoDS order. POST to /orders/{id}/cancel
        returns HTTP 200 + empty body on success; the base
        HTTP layer maps 4xx cancellations (already shipped,
        not found) to AdapterError."""
        self._validate_cancel_order(params)
        oid = str(params["order_id"])
        data = self._autods_request(
            "POST", f"/orders/{oid}/cancel", body={},
        )
        record = {
            "order_id": oid,
            "status": "cancelled",
            "raw_payload": data,
        }
        return self._build_order_response(
            capability, record, raw=data,
        )

    def _do_list_orders(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Paginated list of AutoDS orders. Used for the
        daily reconciliation sweep."""
        page = max(1, int(params.get("page", 1) or 1))
        page_size = max(1, min(
            int(params.get("page_size", 50) or 50), 200,
        ))
        status = params.get("status")
        request_params: dict[str, Any] = {
            "page": page,
            "limit": page_size,
        }
        if status:
            request_params["status"] = str(status)
        data = self._autods_request(
            "GET", "/orders", params=request_params,
        )
        rows = (
            data.get("results")
            or data.get("orders")
            or data.get("list")
            or []
        )
        out: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                out.append(_extract_autods_order_status(
                    row, str(row.get("id") or row.get("orderId") or ""),
                ))
        normalised = [
            self._normalise_order(r, default_source=self.name)
            for r in out
        ]
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source": self.name,
                "orders": normalised,
                "total": len(normalised),
                "page": page,
                "page_size": page_size,
            },
            raw=data,
        )

    def _do_get_variant_stock(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Stock lookup via AutoDS's product detail endpoint
        (AutoDS has no dedicated stock endpoint — the product
        detail response carries per-variant ``stock`` counts)."""
        self._validate_get_variant_stock(params)
        vid = str(params["variant_id"])
        # variant_id on AutoDS is ``<product_id>:<variant_id>``.
        # Callers that know only one half pass the full combined
        # id; we split on ":" when present, otherwise use the
        # single id as the product id (AutoDS returns all
        # variants in that case).
        if ":" in vid:
            pid, vid_only = vid.split(":", 1)
        else:
            pid, vid_only = vid, ""
        data = self._autods_request(
            "GET", f"/products/{pid}",
        )
        record = _extract_autods_product(data)
        variants = record.get("variants") or []
        target_stock = 0
        if vid_only:
            for v in variants:
                if str(v.get("variant_id") or "") == vid_only:
                    try:
                        target_stock = int(v.get("stock") or 0)
                    except (TypeError, ValueError):
                        target_stock = 0
                    break
        else:
            for v in variants:
                try:
                    target_stock += max(
                        0, int(v.get("stock") or 0),
                    )
                except (TypeError, ValueError):
                    continue
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source": self.name,
                "variant_id": vid,
                "stock": target_stock,
                "in_stock": target_stock > 0,
                "warehouses": [],
            },
            raw=data,
        )


# ---------------------------------------------------------------------------
# Response extractors — convert AutoDS JSON to the canonical
# shape ``SourcingBaseAdapter._normalise_product`` /
# ``_normalise_order`` expect.
# ---------------------------------------------------------------------------


def _extract_autods_search(
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Pull the product list out of an AutoDS search response.

    The search endpoint returns ``{"results": [...], "total": N,
    "page": N}``. Some older API versions use ``"items"`` —
    check both."""
    if not isinstance(data, dict):
        return []
    for key in ("results", "items", "products", "list"):
        records = data.get(key)
        if isinstance(records, list):
            return [r for r in records if isinstance(r, dict)]
    return []


def _f(value: Any, default: float = 0.0) -> float:
    """Best-effort float coerce — AutoDS sometimes returns
    strings like ``"29.99"`` and sometimes bare numbers."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _s(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _extract_autods_product(
    data: dict[str, Any],
) -> dict[str, Any]:
    """Map an AutoDS product payload to the canonical record
    shape.

    Expected AutoDS fields (per their docs):
      * id                — sourcing_id
      * title             — title
      * description       — description (HTML in some cases)
      * category          — category string
      * cost              — supplier cost, USD
      * price             — suggested retail price, USD
      * currency          — usually "USD"
      * images[]          — list of URLs OR {url, position}
      * variants[]        — list of {id, sku, cost, stock,
                            attributes:{size,color,...}}
      * shipping_days_min / shipping_days_max
      * origin_country    — "US", "CN", "DE", etc
      * weight_grams
      * supplier_url      — link back to AutoDS product page
    """
    if not isinstance(data, dict):
        return {}

    images_raw = data.get("images") or []
    images: list[str] = []
    if isinstance(images_raw, list):
        for item in images_raw:
            if isinstance(item, str):
                images.append(item)
            elif isinstance(item, dict):
                url = item.get("url") or item.get("src")
                if url:
                    images.append(str(url))

    variants_raw = data.get("variants") or []
    variants: list[dict[str, Any]] = []
    if isinstance(variants_raw, list):
        for v in variants_raw:
            if not isinstance(v, dict):
                continue
            variants.append({
                "variant_id": _s(v.get("id") or v.get("variant_id")),
                "sku": _s(v.get("sku")),
                "cost_usd": _f(v.get("cost")),
                "attributes": (
                    v.get("attributes")
                    if isinstance(v.get("attributes"), dict)
                    else {}
                ),
                "stock": _i(v.get("stock")),
            })

    return {
        "sourcing_id": _s(
            data.get("id") or data.get("product_id"),
        ),
        "title": _s(data.get("title") or data.get("name")),
        "description": _s(data.get("description")),
        "category": _s(data.get("category")),
        "cost_usd": _f(
            data.get("cost") or data.get("cost_usd"),
        ),
        "suggested_price_usd": _f(
            data.get("price") or data.get("retail_price"),
        ),
        "currency": _s(data.get("currency"), "USD"),
        "images": images,
        "variants": variants,
        "shipping_days_min": _i(data.get("shipping_days_min")),
        "shipping_days_max": _i(data.get("shipping_days_max")),
        "origin_country": _s(data.get("origin_country")),
        "weight_grams": _i(
            data.get("weight_grams") or data.get("weight"),
        ),
        "raw_url": _s(
            data.get("supplier_url")
            or data.get("url")
            or data.get("source_url"),
        ),
    }


def _build_autods_order_body(
    params: dict[str, Any],
) -> dict[str, Any]:
    """Shape the AutoDS ``POST /orders`` payload.

    Input (caller, validated by base) has:
      * items[]: [{variant_id|sku, quantity, cost_usd?}]
      * shipping: {name, address1, address2?, city, state?,
                   zip, country, phone?, email?}
      * note?, order_ref?

    AutoDS expects:
      * items: [{variant_id, quantity}]
      * shipping_address: {...}
      * customer_note, external_order_id
    """
    items_out: list[dict[str, Any]] = []
    for it in params.get("items") or []:
        if not isinstance(it, dict):
            continue
        vid = it.get("variant_id") or it.get("sku")
        if not vid:
            continue
        items_out.append({
            "variant_id": _s(vid),
            "quantity": _i(it.get("quantity"), 1),
        })

    shipping = params.get("shipping") or {}
    if not isinstance(shipping, dict):
        shipping = {}

    body: dict[str, Any] = {
        "items": items_out,
        "shipping_address": {
            "name": _s(shipping.get("name")),
            "address1": _s(shipping.get("address1")),
            "address2": _s(shipping.get("address2")),
            "city": _s(shipping.get("city")),
            "state": _s(shipping.get("state")),
            "zip": _s(shipping.get("zip")),
            "country": _s(shipping.get("country")),
            "phone": _s(shipping.get("phone")),
            "email": _s(shipping.get("email")),
        },
    }
    if params.get("note"):
        body["customer_note"] = _s(params.get("note"))
    if params.get("order_ref"):
        body["external_order_id"] = _s(params.get("order_ref"))
    return body


def _extract_autods_order_ack(
    data: dict[str, Any], original_params: dict[str, Any],
) -> dict[str, Any]:
    """After POST /orders — AutoDS returns the created order
    record with a fresh ``id`` + ``status`` (usually
    "pending")."""
    if not isinstance(data, dict):
        data = {}
    return {
        "order_id": _s(
            data.get("id") or data.get("order_id"),
        ),
        "status": _s(data.get("status"), "pending").lower(),
        "tracking_number": _s(data.get("tracking_number")),
        "tracking_url": _s(data.get("tracking_url")),
        "carrier": _s(data.get("carrier")),
        "shipped_at": _s(data.get("shipped_at")),
        "delivered_at": _s(data.get("delivered_at")),
        "items": _map_order_items(
            data.get("items")
            or original_params.get("items")
            or [],
        ),
        "external_order_id": _s(data.get("external_order_id")),
    }


def _extract_autods_order_status(
    data: dict[str, Any], order_id: str,
) -> dict[str, Any]:
    """After GET /orders/{id} — same shape as ack but with
    populated tracking + ship dates once AutoDS fulfils."""
    if not isinstance(data, dict):
        data = {}
    return {
        "order_id": _s(
            data.get("id") or data.get("order_id") or order_id,
        ),
        "status": _s(data.get("status"), "pending").lower(),
        "tracking_number": _s(data.get("tracking_number")),
        "tracking_url": _s(data.get("tracking_url")),
        "carrier": _s(data.get("carrier")),
        "shipped_at": _s(data.get("shipped_at")),
        "delivered_at": _s(data.get("delivered_at")),
        "items": _map_order_items(data.get("items") or []),
        "external_order_id": _s(data.get("external_order_id")),
    }


def _map_order_items(
    items: list[Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "sourcing_id": _s(
                it.get("sourcing_id")
                or it.get("product_id"),
            ),
            "variant_id": _s(it.get("variant_id")),
            "sku": _s(it.get("sku")),
            "quantity": _i(it.get("quantity"), 1),
            "cost_usd": _f(it.get("cost_usd") or it.get("cost")),
        })
    return out
