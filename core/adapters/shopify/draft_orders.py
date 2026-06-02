"""ShopifyDraftOrdersAdapter — cart abandon recovery and bespoke quotes.

Draft orders are Shopify's "shopping cart you build server-side and hand
to a customer for one-click checkout" primitive. ShopAI uses them for
two flows:

  1. **Cart abandon recovery.** When a customer abandons a checkout, the
     engine reconstructs their cart as a draft order, applies a recovery
     discount, and emails them an `invoiceUrl` that pre-fills checkout.
  2. **Bespoke quotes.** B2B / VIP customers ask for custom pricing on
     specific SKUs; the engine packages the quote as a draft order so
     the customer can pay it without sales-rep round-trips.

Both flows want the same shape: line items + customer + discount → draft
order with an `invoiceUrl` that the customer clicks to complete the
purchase.

Capabilities:

  * ``SHOPIFY_CREATE_DRAFT_ORDER`` — create a draft via
    ``draftOrderCreate``. Returns the draft id, status, total, and
    ``invoiceUrl`` (the magic checkout link).
  * ``SHOPIFY_COMPLETE_DRAFT_ORDER`` — convert a draft into a real
    order via ``draftOrderComplete``. Used when the customer has paid
    out-of-band and the engine just needs to record the sale.
  * ``SHOPIFY_LIST_DRAFT_ORDERS`` — page through existing drafts with
    cursor + status filter.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CREATE_DRAFT_MUTATION = """
mutation draftOrderCreate($input: DraftOrderInput!) {
  draftOrderCreate(input: $input) {
    draftOrder {
      id
      name
      status
      invoiceUrl
      totalPriceSet {
        presentmentMoney {
          amount
          currencyCode
        }
      }
      subtotalPriceSet {
        presentmentMoney {
          amount
          currencyCode
        }
      }
      currencyCode
      createdAt
      updatedAt
      lineItems(first: 50) {
        edges {
          node {
            title
            quantity
            originalUnitPriceSet {
              presentmentMoney { amount currencyCode }
            }
          }
        }
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_COMPLETE_DRAFT_MUTATION = """
mutation draftOrderComplete($id: ID!, $paymentPending: Boolean) {
  draftOrderComplete(id: $id, paymentPending: $paymentPending) {
    draftOrder {
      id
      status
      order {
        id
        name
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_LIST_DRAFTS_QUERY = """
query draftOrders($first: Int!, $after: String, $query: String) {
  draftOrders(first: $first, after: $after, query: $query) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        status
        invoiceUrl
        totalPriceSet {
          presentmentMoney { amount currencyCode }
        }
        subtotalPriceSet {
          presentmentMoney { amount currencyCode }
        }
        createdAt
        updatedAt
      }
    }
  }
}
""".strip()


# Shopify caps draftOrders pagination at 250 per call. Default low to
# stay under the cost budget; callers needing more can paginate.
_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyDraftOrdersAdapter(ShopifyBaseAdapter):
    name = "shopify_draft_orders"
    capabilities = {
        Capability.SHOPIFY_CREATE_DRAFT_ORDER,
        Capability.SHOPIFY_COMPLETE_DRAFT_ORDER,
        Capability.SHOPIFY_LIST_DRAFT_ORDERS,
    }
    # Draft orders use the same scope pair as orders.
    required_scopes = frozenset({
        "read_draft_orders", "write_draft_orders",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_DRAFT_ORDER:
            return self._create_draft(params)
        if capability == Capability.SHOPIFY_COMPLETE_DRAFT_ORDER:
            return self._complete_draft(params)
        if capability == Capability.SHOPIFY_LIST_DRAFT_ORDERS:
            return self._list_drafts(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create_draft(self, params: dict[str, Any]) -> Any:
        draft_input = self._build_draft_input(params)
        data = self._gql(
            _CREATE_DRAFT_MUTATION,
            {"input": draft_input},
        )
        self._check_user_errors(data, "draftOrderCreate")
        payload = data.get("draftOrderCreate") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_DRAFT_ORDER,
            data={"draft_order": self._normalise_draft(payload.get("draftOrder") or {})},
        )

    @staticmethod
    def _build_draft_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into ``DraftOrderInput``.

        Accepts::

            {
                "line_items": [
                    {"variant_id": "gid://shopify/ProductVariant/123",
                     "quantity": 2,
                     "applied_discount": {"value_type": "PERCENTAGE",
                                          "value": 10}},
                    # OR a custom item without a variant:
                    {"title": "Custom service",
                     "quantity": 1,
                     "original_unit_price": "50.00"},
                ],
                "customer_id": "gid://shopify/Customer/456",  # optional
                "email": "buyer@example.com",                  # optional
                "note": "Recovery cart for X",                 # optional
                "tags": ["recovery", "shopai"],                # optional
                "use_customer_default_address": True,          # optional
            }

        Validation runs before the GraphQL hop so misuse fails fast.
        """
        line_items = params.get("line_items")
        if not isinstance(line_items, list) or not line_items:
            raise AdapterValidationError(
                "shopify_draft_orders",
                "'line_items' must be a non-empty list",
            )

        out_line_items: list[dict[str, Any]] = []
        for i, li in enumerate(line_items):
            if not isinstance(li, dict):
                raise AdapterValidationError(
                    "shopify_draft_orders", f"line_items[{i}] is not a dict",
                )
            qty = li.get("quantity", 1)
            try:
                qty = int(qty)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_draft_orders",
                    f"line_items[{i}] 'quantity' must be int, got {type(qty).__name__}",
                ) from exc
            if qty <= 0:
                raise AdapterValidationError(
                    "shopify_draft_orders",
                    f"line_items[{i}] 'quantity' must be > 0, got {qty}",
                )

            variant_id = li.get("variant_id") or li.get("variantId")
            title = li.get("title")
            original_unit_price = (
                li.get("original_unit_price") or li.get("originalUnitPrice")
            )
            if not variant_id and not title:
                raise AdapterValidationError(
                    "shopify_draft_orders",
                    f"line_items[{i}] needs either 'variant_id' or 'title'",
                )
            # Custom (non-variant) items must carry their own price; the
            # variant path inherits the variant's price by default.
            if not variant_id and original_unit_price is None:
                raise AdapterValidationError(
                    "shopify_draft_orders",
                    f"line_items[{i}] custom item needs 'original_unit_price'",
                )

            entry: dict[str, Any] = {"quantity": qty}
            if variant_id:
                entry["variantId"] = variant_id
            if title:
                if not isinstance(title, str):
                    raise AdapterValidationError(
                        "shopify_draft_orders",
                        f"line_items[{i}] 'title' must be a string",
                    )
                entry["title"] = title
            if original_unit_price is not None:
                # Shopify wants Decimal-as-string; coerce numeric inputs
                # so callers can pass floats/ints without ceremony.
                try:
                    entry["originalUnitPrice"] = f"{float(original_unit_price):.2f}"
                except (TypeError, ValueError) as exc:
                    raise AdapterValidationError(
                        "shopify_draft_orders",
                        f"line_items[{i}] 'original_unit_price' must be numeric",
                    ) from exc
            applied_discount = li.get("applied_discount") or li.get("appliedDiscount")
            if applied_discount is not None:
                entry["appliedDiscount"] = _normalise_applied_discount(
                    applied_discount, where=f"line_items[{i}]",
                )
            out_line_items.append(entry)

        out: dict[str, Any] = {"lineItems": out_line_items}

        customer_id = params.get("customer_id") or params.get("customerId")
        if customer_id:
            if not isinstance(customer_id, str):
                raise AdapterValidationError(
                    "shopify_draft_orders",
                    "'customer_id' must be a Shopify GID string",
                )
            out["purchasingEntity"] = {"customerId": customer_id}

        email = params.get("email")
        if email:
            if not isinstance(email, str) or "@" not in email:
                raise AdapterValidationError(
                    "shopify_draft_orders",
                    "'email' must be a valid email string",
                )
            out["email"] = email

        note = params.get("note")
        if note:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    "shopify_draft_orders", "'note' must be a string",
                )
            out["note"] = note

        tags = params.get("tags")
        if tags is not None:
            if isinstance(tags, list):
                out["tags"] = [str(t) for t in tags if t]
            elif isinstance(tags, str):
                out["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
            else:
                raise AdapterValidationError(
                    "shopify_draft_orders",
                    "'tags' must be list[str] or comma-separated string",
                )

        use_default_addr = params.get("use_customer_default_address")
        if use_default_addr is not None:
            out["useCustomerDefaultAddress"] = bool(use_default_addr)

        applied_order_discount = params.get("applied_discount") or params.get(
            "appliedDiscount"
        )
        if applied_order_discount is not None:
            out["appliedDiscount"] = _normalise_applied_discount(
                applied_order_discount, where="order",
            )

        return out

    # ── Complete ───────────────────────────────────────────────────

    def _complete_draft(self, params: dict[str, Any]) -> Any:
        draft_id = params.get("id") or params.get("draft_order_id")
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise AdapterValidationError(
                "shopify_draft_orders",
                "'id' (Shopify GID for the draft order) is required",
            )
        payment_pending = bool(params.get("payment_pending", False))
        data = self._gql(
            _COMPLETE_DRAFT_MUTATION,
            {"id": draft_id.strip(), "paymentPending": payment_pending},
        )
        self._check_user_errors(data, "draftOrderComplete")
        payload = data.get("draftOrderComplete") or {}
        draft = payload.get("draftOrder") or {}
        order = draft.get("order") or {}
        return self._success(
            Capability.SHOPIFY_COMPLETE_DRAFT_ORDER,
            data={
                "draft_order_id": draft.get("id", ""),
                "status": draft.get("status", ""),
                "order_id": order.get("id", "") if isinstance(order, dict) else "",
                "order_name": order.get("name", "") if isinstance(order, dict) else "",
            },
        )

    # ── List ───────────────────────────────────────────────────────

    def _list_drafts(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_draft_orders", "'cursor' must be a string or None",
            )
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                "shopify_draft_orders", "'query' must be a string or None",
            )

        data = self._gql(
            _LIST_DRAFTS_QUERY,
            {"first": limit, "after": cursor, "query": query},
        )
        envelope = data.get("draftOrders") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        drafts = [
            self._normalise_draft(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_DRAFT_ORDERS,
            data={
                "draft_orders": drafts,
                "count": len(drafts),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _normalise_draft(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}

        def _money(field_name: str) -> tuple[float, str]:
            field = node.get(field_name) or {}
            money = (field.get("presentmentMoney") if isinstance(field, dict) else None) or {}
            try:
                amt = float(money.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            return amt, money.get("currencyCode", "") or ""

        total, currency = _money("totalPriceSet")
        subtotal, _ = _money("subtotalPriceSet")
        line_items: list[dict[str, Any]] = []
        li_envelope = node.get("lineItems") or {}
        if isinstance(li_envelope, dict):
            for edge in li_envelope.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                li_node = edge.get("node") or {}
                price_field = li_node.get("originalUnitPriceSet") or {}
                price_money = (
                    price_field.get("presentmentMoney")
                    if isinstance(price_field, dict) else None
                ) or {}
                try:
                    unit_price = float(price_money.get("amount", 0) or 0)
                except (TypeError, ValueError):
                    unit_price = 0.0
                line_items.append({
                    "title": li_node.get("title", "") or "",
                    "quantity": int(li_node.get("quantity", 0) or 0),
                    "unit_price": unit_price,
                })
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "status": node.get("status", "") or "",
            "invoice_url": node.get("invoiceUrl", "") or "",
            "total": total,
            "subtotal": subtotal,
            "currency": currency or (node.get("currencyCode", "") or ""),
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "line_items": line_items,
        }


def _normalise_applied_discount(
    raw: Any, *, where: str,
) -> dict[str, Any]:
    """Translate a friendly applied-discount dict into Shopify's
    ``DraftOrderAppliedDiscountInput`` shape.

    Friendly form::

        {"value_type": "PERCENTAGE" | "FIXED_AMOUNT",
         "value": 10,
         "title": "Recovery 10% off",  # optional
         "description": "..."}          # optional
    """
    if not isinstance(raw, dict):
        raise AdapterValidationError(
            "shopify_draft_orders",
            f"{where} 'applied_discount' must be a dict",
        )
    # W962-66 Pattern G monetary fix: distinguish missing key
    # from explicit empty value. Pre-fix `raw.get("value_type")
    # or raw.get("valueType") or "PERCENTAGE"` would silently
    # flip an explicit empty-string value to PERCENTAGE (i.e.
    # 10 / 100 = 10% off instead of $10 off -- 10x revenue
    # impact difference). Now: explicit empty string raises;
    # only truly-missing key defaults.
    _MISSING = object()
    vt_snake = raw.get("value_type", _MISSING)
    vt_camel = raw.get("valueType", _MISSING)
    if vt_snake is _MISSING and vt_camel is _MISSING:
        value_type = "PERCENTAGE"
    elif vt_snake is not _MISSING and vt_snake == "":
        raise AdapterValidationError(
            "shopify_draft_orders",
            f"{where} 'applied_discount.value_type' was "
            "explicit empty string. Provide PERCENTAGE or "
            "FIXED_AMOUNT, or omit the key for the default.",
        )
    elif vt_camel is not _MISSING and vt_camel == "":
        raise AdapterValidationError(
            "shopify_draft_orders",
            f"{where} 'applied_discount.valueType' was "
            "explicit empty string. Provide PERCENTAGE or "
            "FIXED_AMOUNT, or omit the key for the default.",
        )
    else:
        value_type = (
            vt_snake if vt_snake is not _MISSING else vt_camel
        )
    if not isinstance(value_type, str):
        raise AdapterValidationError(
            "shopify_draft_orders",
            f"{where} 'applied_discount.value_type' must be a string",
        )
    value_type = value_type.upper()
    if value_type not in ("PERCENTAGE", "FIXED_AMOUNT"):
        raise AdapterValidationError(
            "shopify_draft_orders",
            f"{where} 'applied_discount.value_type' must be "
            f"PERCENTAGE or FIXED_AMOUNT, got {value_type!r}",
        )
    value = raw.get("value")
    try:
        value_num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise AdapterValidationError(
            "shopify_draft_orders",
            f"{where} 'applied_discount.value' must be numeric, "
            f"got {type(value).__name__}",
        ) from exc
    if value_num <= 0:
        raise AdapterValidationError(
            "shopify_draft_orders",
            f"{where} 'applied_discount.value' must be > 0, got {value_num}",
        )
    if value_type == "PERCENTAGE" and value_num > 100:
        raise AdapterValidationError(
            "shopify_draft_orders",
            f"{where} 'applied_discount.value' must be <= 100 "
            f"for PERCENTAGE, got {value_num}",
        )

    out: dict[str, Any] = {
        "valueType": value_type,
        "value": value_num,
    }
    title = raw.get("title")
    if title:
        if not isinstance(title, str):
            raise AdapterValidationError(
                "shopify_draft_orders",
                f"{where} 'applied_discount.title' must be a string",
            )
        out["title"] = title
    description = raw.get("description")
    if description:
        if not isinstance(description, str):
            raise AdapterValidationError(
                "shopify_draft_orders",
                f"{where} 'applied_discount.description' must be a string",
            )
        out["description"] = description
    return out
