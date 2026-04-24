"""CJDropshippingAdapter — free supplier API, MN-friendly fulfillment.

CJ Dropshipping (https://developers.cjdropshipping.com) provides
a free developer API. Crucially for a Mongolia-based operator:

  * No US entity required — individual dropshippers are welcome
  * Accounts can be funded via PayPal, Payoneer, or Wise
  * Ships worldwide from CN / US / DE / TH warehouses

That combination makes CJ the sub-$500-budget fulfillment path
this codebase targets as its first real sourcing integration.

Authentication: two credentials (``email`` + ``password``) are
POSTed to ``/api2.0/v1/authentication/getAccessToken`` to exchange
them for an access token that's then sent in the ``CJ-Access-Token``
header on every subsequent call. Tokens are valid for 7 days per
CJ's docs; the adapter caches them in-memory and re-fetches on
auth failure.

Endpoints used:

  * ``POST /api2.0/v1/authentication/getAccessToken``  — login
  * ``GET  /api2.0/v1/product/list``                   — keyword search
  * ``GET  /api2.0/v1/product/query``                  — product detail
  * ``POST /api2.0/v1/shopping/order/createOrder``     — submit order
  * ``GET  /api2.0/v1/shopping/order/getOrderDetail``  — poll status

CJ's response envelope is uniform: ``{"code": 200, "result": true,
"message": "...", "data": {...}}``. ``code != 200`` or
``result == false`` signals a logical failure even though the
HTTP status is 200.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from utils.logger import get_logger

from ..base import AdapterResult, Capability
from ..config import get_config
from ..errors import (
    AdapterAuthError,
    AdapterError,
    AdapterNotConfigured,
)
from ._base import SourcingBaseAdapter

logger = get_logger("adapters.sourcing.cj_dropshipping")


# Access tokens are valid for 7 days per CJ docs. We refresh at
# 6 days to leave headroom for clock skew.
_TOKEN_TTL_SECONDS = 6 * 24 * 3600


class CJDropshippingAdapter(SourcingBaseAdapter):
    name = "cj_dropshipping"
    base_url = "https://developers.cjdropshipping.com/api2.0/v1"

    # Two-credential auth — config_alias is a sentinel for the
    # primary credential; we read both ``cj_email`` and
    # ``cj_password`` in ``is_configured()``.
    config_alias = "cj_email"
    _email_alias = "cj_email"
    _password_alias = "cj_password"

    capabilities = {
        Capability.SOURCING_SEARCH_PRODUCTS,
        Capability.SOURCING_GET_PRODUCT,
        Capability.SOURCING_CREATE_ORDER,
        Capability.SOURCING_GET_ORDER_STATUS,
        Capability.SOURCING_CANCEL_ORDER,
        Capability.SOURCING_LIST_ORDERS,
        Capability.SOURCING_GET_SHIPPING_METHODS,
        Capability.SOURCING_GET_VARIANT_STOCK,
    }

    # Primary supplier — highest priority among sourcing adapters.
    # AutoDS / Spocket will slot in at 70-80 when added.
    priority = 90
    # Catalog queries are free; order placement cost is the item
    # cost itself (not a per-call fee).
    cost_per_call = 0.0
    requires_key = True

    def __init__(self) -> None:
        super().__init__()
        self._token: str = ""
        self._token_expires_at: float = 0.0
        self._token_lock = threading.Lock()

    # ── Configuration ──────────────────────────────────────────

    def is_configured(self) -> bool:
        cfg = get_config()
        return bool(
            self.base_url
            and cfg.get(self._email_alias)
            and cfg.get(self._password_alias),
        )

    def _credentials(self) -> tuple[str, str]:
        cfg = get_config()
        email = cfg.get(self._email_alias) or ""
        password = cfg.get(self._password_alias) or ""
        if not email or not password:
            env_e = cfg.env_var_for(self._email_alias) or self._email_alias
            env_p = cfg.env_var_for(self._password_alias) or self._password_alias
            raise AdapterNotConfigured(
                self.name,
                f"missing credentials (set ${env_e} + ${env_p})",
            )
        return email, password

    # ── Token management ───────────────────────────────────────

    def _get_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid access token, fetching / refreshing as needed."""
        now = time.time()
        with self._token_lock:
            if (
                not force_refresh
                and self._token
                and now < self._token_expires_at
            ):
                return self._token

            email, password = self._credentials()
            url = f"{self.base_url}/authentication/getAccessToken"
            # Auth call needs no token, just a plain JSON body.
            raw = self._http_request(
                "POST",
                url,
                body={"email": email, "password": password},
                headers={
                    "Accept":     "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "ShopAI-Sourcing/1.0",
                },
            )
            token = _extract_access_token(raw)
            if not token:
                msg = _extract_error_message(raw) or "no accessToken in response"
                raise AdapterAuthError(
                    self.name, f"CJ token exchange failed: {msg}",
                )
            self._token = token
            self._token_expires_at = now + _TOKEN_TTL_SECONDS
            return token

    def _auth_headers(self) -> dict[str, str]:
        token = self._get_token()
        return {
            "CJ-Access-Token": token,
            "Accept":          "application/json",
            "Content-Type":    "application/json",
            "User-Agent":      "ShopAI-Sourcing/1.0",
        }

    def _cj_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call a CJ endpoint and unwrap the ``data`` envelope.

        On ``401 Unauthorized`` (token expired before TTL — possible
        if CJ invalidated it out of band) we refresh once and retry.
        All other errors propagate up as typed AdapterError.
        """
        url = f"{self.base_url}{path}"
        try:
            raw = self._http_request(
                method, url, body=body, params=params,
            )
        except AdapterAuthError:
            # Invalidate cache + retry once with a fresh token.
            with self._token_lock:
                self._token = ""
                self._token_expires_at = 0.0
            self._get_token(force_refresh=True)
            raw = self._http_request(
                method, url, body=body, params=params,
            )

        if not isinstance(raw, dict):
            raise AdapterError(
                self.name, f"CJ returned non-object: {type(raw).__name__}",
            )
        code = raw.get("code")
        result = raw.get("result")
        if code is not None and code != 200:
            raise AdapterError(
                self.name,
                f"CJ logical failure code={code}: "
                f"{_extract_error_message(raw)}",
            )
        if result is False:
            raise AdapterError(
                self.name,
                f"CJ logical failure: {_extract_error_message(raw)}",
            )
        data = raw.get("data")
        if not isinstance(data, dict):
            # Some endpoints return lists under 'data' — wrap so
            # callers can rely on dict access.
            if isinstance(data, list):
                return {"list": data, "_raw": raw}
            return {"_raw": raw}
        data["_raw"] = raw
        return data

    # ── Capability implementations ─────────────────────────────

    def _do_search_products(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_search_products(params)
        query = str(params["query"])
        limit = int(params.get("limit", 20))
        page_num = int(params.get("page", 1) or 1)
        query_params: dict[str, Any] = {
            "keyWords": query,
            "pageSize": limit,
            "pageNum":  page_num,
        }
        data = self._cj_request(
            "GET", "/product/list", params=query_params,
        )
        records = _extract_cj_products(data)
        return self._build_products_response(
            capability, records, query=query, raw=data.get("_raw"),
        )

    def _do_get_product(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_get_product(params)
        pid = str(params.get("sourcing_id") or params.get("product_id"))
        data = self._cj_request(
            "GET", "/product/query", params={"pid": pid},
        )
        record = _extract_cj_product_detail(data)
        return self._build_product_response(
            capability, record, raw=data.get("_raw"),
        )

    def _do_create_order(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_create_order(params)
        body = _build_cj_order_body(params)
        data = self._cj_request(
            "POST", "/shopping/order/createOrder", body=body,
        )
        record = _extract_cj_order_ack(data, params)
        return self._build_order_response(
            capability, record, raw=data.get("_raw"),
        )

    def _do_get_order_status(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        self._validate_get_order_status(params)
        oid = str(params["order_id"])
        data = self._cj_request(
            "GET", "/shopping/order/getOrderDetail", params={"orderId": oid},
        )
        record = _extract_cj_order_status(data, oid)
        return self._build_order_response(
            capability, record, raw=data.get("_raw"),
        )

    # ── Wave 5 — cancel + list + shipping + stock ───────────────

    def _do_cancel_order(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Cancel a CJ supplier order. Must be called before
        CJ ships it — post-ship cancels are refused by CJ
        itself (returns a 4xx that bubbles up as AdapterError).
        §4b.D: cancelling an already-cancelled order returns
        CJ's idempotent ACK."""
        self._validate_cancel_order(params)
        oid = str(params["order_id"])
        data = self._cj_request(
            "POST", "/shopping/order/cancelOrder",
            body={"orderId": oid},
        )
        record = {
            "order_id": oid,
            "status": "cancelled",
            "raw_payload": data,
        }
        return self._build_order_response(
            capability, record, raw=data.get("_raw"),
        )

    def _do_list_orders(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Paginated list of orders. Useful for a daily
        reconciliation sweep — comparing CJ's order state to
        our local Shopify fulfillment records."""
        page = max(1, int(params.get("page", 1) or 1))
        page_size = max(1, min(int(params.get("page_size", 50) or 50), 200))
        status = params.get("status")
        request_params: dict[str, Any] = {
            "pageNum": page,
            "pageSize": page_size,
        }
        if status:
            request_params["status"] = str(status)
        data = self._cj_request(
            "GET", "/shopping/order/list", params=request_params,
        )
        rows = data.get("list") or data.get("orders") or []
        out: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                out.append(
                    self._normalise_order({
                        "order_id": str(
                            row.get("orderId")
                            or row.get("orderNum")
                            or "",
                        ),
                        "status": _map_status(
                            str(row.get("orderStatus") or "")
                        ),
                        "tracking_number": str(
                            row.get("trackingNumber") or "",
                        ),
                        "cost_usd": row.get("orderAmount"),
                        "raw_payload": row,
                    }),
                )
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source": self.name,
                "orders": out,
                "total": len(out),
                "page": page,
                "page_size": page_size,
            },
            raw=data.get("_raw"),
        )

    def _do_get_shipping_methods(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Quote available shipping options for a CJ variant
        to a destination country. Used by the product_launch
        orchestrator before import to reject products whose
        fastest route > 14 days (dropshipping kill threshold).
        """
        self._validate_get_shipping_methods(params)
        vid = str(params["variant_id"])
        country = str(params["country"]).upper()
        quantity = max(1, int(params.get("quantity", 1) or 1))
        data = self._cj_request(
            "POST", "/logistic/freightCalculate",
            body={
                "vid": vid,
                "countryCode": country,
                "quantity": quantity,
            },
        )
        methods_raw = (
            data.get("list") or data.get("methods") or []
        )
        methods: list[dict[str, Any]] = []
        if isinstance(methods_raw, list):
            for m in methods_raw:
                if not isinstance(m, dict):
                    continue
                try:
                    cost = float(
                        m.get("logisticPrice")
                        or m.get("price")
                        or 0,
                    )
                except (TypeError, ValueError):
                    cost = 0.0
                try:
                    days_min = int(
                        m.get("logisticAging")
                        or m.get("daysMin")
                        or 0,
                    )
                except (TypeError, ValueError):
                    days_min = 0
                try:
                    days_max = int(
                        m.get("logisticAgingMax")
                        or m.get("daysMax")
                        or days_min,
                    )
                except (TypeError, ValueError):
                    days_max = days_min
                methods.append({
                    "method_name": str(
                        m.get("logisticName")
                        or m.get("name")
                        or "",
                    ),
                    "cost_usd": cost,
                    "currency": "USD",
                    "days_min": days_min,
                    "days_max": days_max,
                    "tracked": bool(m.get("tracked", True)),
                })
        methods.sort(key=lambda x: (
            x["days_max"] or 999, x["cost_usd"] or 999,
        ))
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source":   self.name,
                "variant_id": vid,
                "country":  country,
                "methods":  methods,
                "fastest":  methods[0] if methods else None,
                "cheapest": (
                    min(methods, key=lambda x: x["cost_usd"])
                    if methods else None
                ),
            },
            raw=data.get("_raw"),
        )

    def _do_get_variant_stock(
        self, capability: Capability, params: dict[str, Any],
    ) -> AdapterResult:
        """Live stock check for a CJ variant. Used before
        importing a winner to Shopify — avoids listing SKUs
        that supplier just ran out of."""
        self._validate_get_variant_stock(params)
        vid = str(params["variant_id"])
        data = self._cj_request(
            "GET", "/product/stock/queryByVid",
            params={"vid": vid},
        )
        rows = (
            data.get("list") or data.get("stockList") or []
        )
        stock = 0
        warehouses: list[dict[str, Any]] = []
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    qty = int(r.get("stock") or r.get("num") or 0)
                except (TypeError, ValueError):
                    qty = 0
                stock += max(0, qty)
                warehouses.append({
                    "warehouse": str(
                        r.get("areaEn") or r.get("area") or "",
                    ),
                    "stock": max(0, qty),
                })
        return AdapterResult.success(
            adapter=self.name,
            capability=capability.value,
            data={
                "source": self.name,
                "variant_id": vid,
                "stock": stock,
                "in_stock": stock > 0,
                "warehouses": warehouses,
            },
            raw=data.get("_raw"),
        )


# ---------------------------------------------------------------------------
# Response extractors
# ---------------------------------------------------------------------------


# CJ's order-status vocabulary → our canonical 5-state model.
_STATUS_MAP = {
    "created":       "pending",
    "unpaid":        "pending",
    "paid":          "processing",
    "processing":    "processing",
    "picking":       "processing",
    "in_process":    "processing",
    "packaging":     "processing",
    "shipped":       "shipped",
    "in_transit":    "shipped",
    "transit":       "shipped",
    "delivered":     "delivered",
    "completed":     "delivered",
    "cancelled":     "cancelled",
    "canceled":      "cancelled",
    "refunded":      "cancelled",
}


def _map_status(raw: str) -> str:
    key = (raw or "").strip().lower().replace(" ", "_")
    return _STATUS_MAP.get(key, "processing")


def _extract_access_token(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    data = raw.get("data")
    if isinstance(data, dict):
        tok = data.get("accessToken") or data.get("access_token")
        if tok:
            return str(tok)
    # Some CJ responses put the token at the top level.
    tok = raw.get("accessToken") or raw.get("access_token")
    return str(tok) if tok else ""


def _extract_error_message(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    return str(
        raw.get("message")
        or raw.get("msg")
        or raw.get("errorMessage")
        or "",
    )


def _extract_cj_products(data: dict[str, Any]) -> list[dict[str, Any]]:
    """CJ search returns ``data.list`` with thin product summaries."""
    items = data.get("list") or data.get("products") or []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for p in items:
        if not isinstance(p, dict):
            continue
        out.append(_product_summary_to_record(p))
    return out


def _product_summary_to_record(p: dict[str, Any]) -> dict[str, Any]:
    images = _split_images(p.get("productImage") or p.get("image") or "")
    try:
        cost = float(p.get("sellPrice", 0) or 0)
    except (TypeError, ValueError):
        cost = 0.0
    # Search results only expose a price range — if so, take the
    # lower bound as supplier cost.
    if cost == 0:
        price_range = str(p.get("priceRange", "") or "")
        if "--" in price_range:
            low = price_range.split("--", 1)[0].strip().lstrip("$")
            try:
                cost = float(low)
            except (TypeError, ValueError):
                cost = 0.0
    return {
        "sourcing_id":    str(p.get("pid", "") or p.get("productId", "") or ""),
        "title":          str(p.get("productName", "") or p.get("productNameEn", "") or ""),
        "description":    "",
        "category":       str(p.get("categoryName", "") or ""),
        "cost_usd":       cost,
        "suggested_price_usd": _to_float(p.get("sellPrice") or 0),
        "currency":       "USD",
        "images":         images,
        "variants":       [],
        "shipping_days_min": 0,
        "shipping_days_max": 0,
        "origin_country": str(p.get("countryCode", "") or ""),
        "weight_grams":   _to_int(p.get("productWeight") or 0),
        "raw_url":        str(p.get("productUrl", "") or ""),
    }


def _extract_cj_product_detail(data: dict[str, Any]) -> dict[str, Any]:
    """``data`` for a single-product query carries variants + images."""
    # CJ returns the product object nested under ``data`` (already
    # unwrapped by _cj_request), but some endpoints wrap again.
    product = data if "pid" in data or "productId" in data else data.get("product")
    if not isinstance(product, dict):
        # Fall back to whatever the server sent.
        product = data

    images = _split_images(
        product.get("productImage") or product.get("productImageSet") or "",
    )

    # Variants live under ``variants`` in CJ detail responses.
    variants_raw = product.get("variants") or []
    if not isinstance(variants_raw, list):
        variants_raw = []
    variants: list[dict[str, Any]] = []
    lowest_cost = 0.0
    for v in variants_raw:
        if not isinstance(v, dict):
            continue
        attrs: dict[str, str] = {}
        # CJ uses ``variantKey`` like "Color-Red / Size-XL" or a
        # structured list. Handle both.
        key = v.get("variantKey") or v.get("variantName") or ""
        if isinstance(key, str) and key:
            for token in key.split("-"):
                token = token.strip()
                if ":" in token:
                    k, sep, val = token.partition(":")
                    attrs[k.strip().lower()] = val.strip()
        try:
            cost = float(v.get("variantSellPrice", 0) or 0)
        except (TypeError, ValueError):
            cost = 0.0
        if lowest_cost == 0 or (cost and cost < lowest_cost):
            lowest_cost = cost
        variants.append({
            "variant_id": str(v.get("vid", "") or ""),
            "sku":        str(v.get("variantSku", "") or ""),
            "cost_usd":   cost,
            "attributes": attrs,
            "stock":      _to_int(v.get("variantStock") or 0),
        })

    try:
        top_cost = float(product.get("sellPrice", 0) or 0)
    except (TypeError, ValueError):
        top_cost = 0.0
    resolved_cost = top_cost or lowest_cost

    return {
        "sourcing_id":    str(
            product.get("pid", "") or product.get("productId", "") or "",
        ),
        "title":          str(product.get("productName", "") or ""),
        "description":    _strip_html(product.get("description", "") or ""),
        "category":       str(product.get("categoryName", "") or ""),
        "cost_usd":       resolved_cost,
        "suggested_price_usd": _to_float(
            product.get("suggestSellPrice") or product.get("sellPrice") or 0,
        ),
        "currency":       "USD",
        "images":         images,
        "variants":       variants,
        "shipping_days_min": _to_int(product.get("minShippingDays") or 0),
        "shipping_days_max": _to_int(product.get("maxShippingDays") or 0),
        "origin_country": str(product.get("sourceFrom", "") or "CN"),
        "weight_grams":   _to_int(product.get("productWeight") or 0),
        "raw_url":        str(product.get("productUrl", "") or ""),
    }


def _build_cj_order_body(params: dict[str, Any]) -> dict[str, Any]:
    """Translate our canonical createOrder params into CJ's body shape."""
    shipping = params.get("shipping") or {}
    items = params.get("items") or []
    products = [
        {
            "vid":      str(it.get("variant_id") or it.get("sku") or ""),
            "quantity": int(it.get("quantity", 1) or 1),
            "shippingName": str(shipping.get("shipping_method", "") or ""),
        }
        for it in items
    ]
    return {
        "orderNumber": str(params.get("external_order_id") or ""),
        "shippingCountryCode": str(shipping.get("country") or ""),
        "shippingProvince":    str(shipping.get("province") or shipping.get("state") or ""),
        "shippingCity":        str(shipping.get("city") or ""),
        "shippingAddress":     str(shipping.get("address1") or ""),
        "shippingAddress2":    str(shipping.get("address2") or ""),
        "shippingCustomerName": str(shipping.get("name") or ""),
        "shippingZip":         str(shipping.get("zip") or ""),
        "shippingPhone":       str(shipping.get("phone") or ""),
        "remark":              str(params.get("remark") or ""),
        "fromCountryCode":     str(params.get("origin_country") or ""),
        "logisticName":        str(shipping.get("shipping_method") or "CJPacket"),
        "products":            products,
    }


def _extract_cj_order_ack(
    data: dict[str, Any], params: dict[str, Any],
) -> dict[str, Any]:
    """createOrder returns just the CJ order id; assemble a record
    so callers get a usable order envelope immediately."""
    oid = str(
        data.get("orderId") or data.get("orderNumber") or "",
    )
    items = params.get("items") or []
    ack_items: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        ack_items.append({
            "sourcing_id": str(it.get("sourcing_id", "") or ""),
            "variant_id":  str(it.get("variant_id") or it.get("sku") or ""),
            "quantity":    _to_int(it.get("quantity", 1) or 1),
            "cost_usd":    _to_float(it.get("cost_usd", 0.0) or 0.0),
        })
    return {
        "order_id":        oid,
        "status":          "pending",
        "items":           ack_items,
        "currency":        "USD",
        "cost_usd":        sum(
            i["cost_usd"] * i["quantity"] for i in ack_items
        ),
    }


def _extract_cj_order_status(
    data: dict[str, Any], order_id: str,
) -> dict[str, Any]:
    detail = data if data.get("orderId") or data.get("orderStatus") else (
        data.get("order") or data
    )
    if not isinstance(detail, dict):
        detail = {}
    status_raw = detail.get("orderStatus") or detail.get("status") or ""
    tracking = detail.get("trackNumber") or detail.get("trackingNumber") or ""
    carrier = detail.get("logisticName") or detail.get("carrier") or ""

    items_raw = detail.get("products") or detail.get("items") or []
    if not isinstance(items_raw, list):
        items_raw = []
    items: list[dict[str, Any]] = []
    for it in items_raw:
        if not isinstance(it, dict):
            continue
        items.append({
            "sourcing_id": str(it.get("pid", "") or it.get("productId", "") or ""),
            "variant_id":  str(it.get("vid", "") or ""),
            "quantity":    _to_int(it.get("quantity", 0) or 0),
            "cost_usd":    _to_float(it.get("sellPrice", 0) or 0),
        })

    return {
        "order_id":        str(detail.get("orderId") or order_id or ""),
        "status":          _map_status(str(status_raw)),
        "tracking_number": str(tracking),
        "tracking_url":    str(detail.get("trackUrl", "") or ""),
        "carrier":         str(carrier),
        "cost_usd":        _to_float(detail.get("orderAmount") or 0),
        "currency":        "USD",
        "items":           items,
        "shipped_at":      str(detail.get("shippedTime", "") or ""),
        "delivered_at":    str(detail.get("deliveredTime", "") or ""),
    }


# ---------------------------------------------------------------------------
# Tiny coercion helpers
# ---------------------------------------------------------------------------


def _to_int(v: Any) -> int:
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def _to_float(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _split_images(value: Any) -> list[str]:
    """CJ returns images as a semicolon- or comma-separated string
    or a list. Normalise to a flat list of URLs."""
    if isinstance(value, list):
        return [str(u) for u in value if u]
    if not isinstance(value, str):
        return []
    if not value:
        return []
    parts = [p.strip() for p in value.replace(",", ";").split(";")]
    return [p for p in parts if p]


def _strip_html(text: str) -> str:
    """CJ descriptions contain HTML; keep a clean text-ish version."""
    import re
    return re.sub(r"<[^>]+>", " ", text or "").strip()
