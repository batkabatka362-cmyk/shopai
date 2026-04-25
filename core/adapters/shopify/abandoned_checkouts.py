"""ShopifyAbandonedCheckoutsAdapter — recover lost carts.

An abandoned checkout is a cart that reached the checkout page but
didn't get paid — the customer entered an email / phone (so we know
who they are) but bailed before completing the purchase. Industry
data says 60-80% of carts get abandoned; even a 5% recovery rate is
material revenue.

ShopAI's marketing engine reads abandoned checkouts to:

  * Trigger the recovery email cadence (T+1h, T+24h, T+72h with
    discount codes that escalate).
  * Score abandonment risk on similar customer profiles for
    pre-empting (cart-saver popup before they leave).
  * Train the LLM creative pipeline on actual abandoned-cart
    contents to generate personalised recovery copy.

Capabilities (read-only — Shopify's send-recovery-email mutation
exists but the engine usually composes via its own ESP rather than
the built-in Shopify recovery template):

  * ``SHOPIFY_LIST_ABANDONED_CHECKOUTS`` — paginated list with
    filter/sort.
  * ``SHOPIFY_GET_ABANDONED_CHECKOUT``   — single checkout with
    full line items + customer.

Pattern E note: ``abandonedCheckouts`` is gated by the
``read_orders`` scope (despite the name — Shopify treats checkouts
as part of the order lifecycle).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CHECKOUT_FIELDS = """
id
name
abandonedCheckoutUrl
createdAt
updatedAt
completedAt
note
taxesIncluded
totalDiscountSet { shopMoney { amount currencyCode } }
totalLineItemsPriceSet { shopMoney { amount currencyCode } }
totalPriceSet { shopMoney { amount currencyCode } }
totalTaxSet { shopMoney { amount currencyCode } }
subtotalPriceSet { shopMoney { amount currencyCode } }
customer {
  id
  email
  firstName
  lastName
  numberOfOrders
}
""".strip()


_CHECKOUT_FIELDS_FULL = f"""
{_CHECKOUT_FIELDS}
lineItems(first: 100) {{
  edges {{
    node {{
      id
      title
      quantity
      sku
      variantTitle
      product {{
        id
        title
      }}
      variant {{
        id
        title
      }}
      originalUnitPriceSet {{ shopMoney {{ amount currencyCode }} }}
      discountedTotalPriceSet {{ shopMoney {{ amount currencyCode }} }}
    }}
  }}
}}
shippingAddress {{
  address1
  address2
  city
  province
  country
  zip
  name
  phone
}}
""".strip()


_LIST_CHECKOUTS_QUERY = f"""
query abandonedCheckouts(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: AbandonedCheckoutSortKeys,
  $reverse: Boolean
) {{
  abandonedCheckouts(
    first: $first,
    after: $after,
    query: $query,
    sortKey: $sortKey,
    reverse: $reverse
  ) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        {_CHECKOUT_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_CHECKOUT_QUERY = f"""
query abandonedCheckout($id: ID!) {{
  abandonedCheckout(id: $id) {{
    {_CHECKOUT_FIELDS_FULL}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

_VALID_SORT_KEYS = {
    "CREATED_AT", "UPDATED_AT", "ID", "RELEVANCE",
}


class ShopifyAbandonedCheckoutsAdapter(ShopifyBaseAdapter):
    name = "shopify_abandoned_checkouts"
    capabilities = {
        Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS,
        Capability.SHOPIFY_GET_ABANDONED_CHECKOUT,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_ABANDONED_CHECKOUT:
            return self._get(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                self.name, "'cursor' must be a string or None",
            )

        variables: dict[str, Any] = {"first": limit, "after": cursor}

        query_filter = params.get("query")
        if query_filter is not None:
            if not isinstance(query_filter, str):
                raise AdapterValidationError(
                    self.name, "'query' must be a string",
                )
            variables["query"] = query_filter

        sort_key = params.get("sort_key")
        if sort_key is not None:
            if not isinstance(sort_key, str) or sort_key not in _VALID_SORT_KEYS:
                raise AdapterValidationError(
                    self.name,
                    f"'sort_key' must be one of: {sorted(_VALID_SORT_KEYS)}",
                )
            variables["sortKey"] = sort_key

        reverse = params.get("reverse")
        if reverse is not None:
            variables["reverse"] = bool(reverse)

        data = self._gql(_LIST_CHECKOUTS_QUERY, variables)
        envelope = data.get("abandonedCheckouts") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        checkouts = [
            self._normalise_checkout(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_ABANDONED_CHECKOUTS,
            data={
                "checkouts": checkouts,
                "count": len(checkouts),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        checkout_id = params.get("id") or params.get("checkout_id")
        if not isinstance(checkout_id, str) or not checkout_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the checkout) is required",
            )
        data = self._gql(_GET_CHECKOUT_QUERY, {"id": checkout_id.strip()})
        node = data.get("abandonedCheckout") or {}
        return self._success(
            Capability.SHOPIFY_GET_ABANDONED_CHECKOUT,
            data={
                "checkout": self._normalise_checkout_full(node),
                "found": bool(node),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _money(envelope: Any) -> tuple[str, str]:
        if not isinstance(envelope, dict):
            return "", ""
        shop_money = envelope.get("shopMoney") or {}
        if not isinstance(shop_money, dict):
            return "", ""
        return (
            shop_money.get("amount", "") or "",
            shop_money.get("currencyCode", "") or "",
        )

    @classmethod
    def _normalise_checkout(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        total_amount, total_currency = cls._money(node.get("totalPriceSet"))
        subtotal_amount, _ = cls._money(node.get("subtotalPriceSet"))
        line_total, _ = cls._money(node.get("totalLineItemsPriceSet"))
        tax_amount, _ = cls._money(node.get("totalTaxSet"))
        discount_amount, _ = cls._money(node.get("totalDiscountSet"))
        customer = node.get("customer") or {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "abandoned_url": node.get("abandonedCheckoutUrl", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "completed_at": node.get("completedAt", "") or "",
            "is_completed": bool(node.get("completedAt")),
            "note": node.get("note", "") or "",
            "taxes_included": bool(node.get("taxesIncluded", False)),
            "total_price": total_amount,
            "subtotal_price": subtotal_amount,
            "line_items_price": line_total,
            "total_tax": tax_amount,
            "total_discount": discount_amount,
            "currency_code": total_currency,
            "customer_id": (
                customer.get("id", "") if isinstance(customer, dict) else ""
            ) or "",
            "customer_email": (
                customer.get("email", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "customer_first_name": (
                customer.get("firstName", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "customer_last_name": (
                customer.get("lastName", "")
                if isinstance(customer, dict) else ""
            ) or "",
            "customer_orders_count": int(
                (customer.get("numberOfOrders") or 0)
                if isinstance(customer, dict) else 0
            ),
        }

    @classmethod
    def _normalise_checkout_full(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        base = cls._normalise_checkout(node)
        if not base:
            return {}
        line_edges = (node.get("lineItems") or {}).get("edges") or []
        base["line_items"] = [
            cls._normalise_line_item(edge.get("node") or {})
            for edge in line_edges if isinstance(edge, dict)
        ]
        addr = node.get("shippingAddress") or {}
        if isinstance(addr, dict) and addr:
            base["shipping_address"] = {
                "name": addr.get("name", "") or "",
                "phone": addr.get("phone", "") or "",
                "address1": addr.get("address1", "") or "",
                "address2": addr.get("address2", "") or "",
                "city": addr.get("city", "") or "",
                "province": addr.get("province", "") or "",
                "country": addr.get("country", "") or "",
                "zip": addr.get("zip", "") or "",
            }
        else:
            base["shipping_address"] = {}
        return base

    @classmethod
    def _normalise_line_item(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        original_amount, _ = cls._money(node.get("originalUnitPriceSet"))
        discounted_total, _ = cls._money(node.get("discountedTotalPriceSet"))
        variant = node.get("variant") or {}
        product = node.get("product") or {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "quantity": int(node.get("quantity") or 0),
            "sku": node.get("sku", "") or "",
            "variant_title": node.get("variantTitle", "") or "",
            "variant_id": (
                variant.get("id", "")
                if isinstance(variant, dict) else ""
            ) or "",
            "product_id": (
                product.get("id", "")
                if isinstance(product, dict) else ""
            ) or "",
            "product_title": (
                product.get("title", "")
                if isinstance(product, dict) else ""
            ) or "",
            "original_unit_price": original_amount,
            "discounted_total_price": discounted_total,
        }
