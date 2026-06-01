"""ShopifyOrdersAdapter — order read + lightweight write surface.

Orders are the central revenue object. ShopAI's analytics, ROAS,
fulfillment, customer-service, and segmentation engines all read
orders; the brain layer occasionally writes back tags / notes to
mark orders as triaged ("flagged-fraud", "vip", "ai-recommended").

Heavy mutations (refund, cancel, edit, fulfillment) live in their
own dedicated adapters — refunds.py, order_edits.py, fulfillment.py.
This adapter intentionally stays read-heavy so concerns remain
separated.

Capabilities:

  * ``SHOPIFY_LIST_ORDERS``    — paginated list with filter/sort.
  * ``SHOPIFY_FETCH_ORDERS``   — alias of ``SHOPIFY_LIST_ORDERS``.
    Engine-side hydrator code consistently uses the ``FETCH_`` form
    (matching ``SHOPIFY_FETCH_CUSTOMERS`` and ``SHOPIFY_FETCH_PRODUCTS``);
    this adapter accepts both so the naming gap doesn't silently
    break the auto-hydration on every order-consuming engine.
  * ``SHOPIFY_GET_ORDER``      — single order with line items + customer.
  * ``SHOPIFY_UPDATE_ORDER``   — update note / customAttributes via
    ``orderUpdate``.
  * ``SHOPIFY_TAG_ORDER``      — add tags via ``tagsAdd`` mutation.
  * ``SHOPIFY_UNTAG_ORDER``    — remove tags via ``tagsRemove``.
  * ``SHOPIFY_CLOSE_ORDER``    — archive/close via ``orderClose``.

The list capability supports the same Shopify search syntax the
admin UI uses (e.g. ``"created_at:>2026-01-01 financial_status:paid
fulfillment_status:unfulfilled"``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_ORDER_FIELDS = """
id
name
email
phone
note
tags
displayFinancialStatus
displayFulfillmentStatus
processedAt
createdAt
updatedAt
cancelledAt
closedAt
currencyCode
totalPriceSet { shopMoney { amount currencyCode } }
subtotalPriceSet { shopMoney { amount currencyCode } }
totalShippingPriceSet { shopMoney { amount currencyCode } }
totalTaxSet { shopMoney { amount currencyCode } }
totalRefundedSet { shopMoney { amount currencyCode } }
customer {
  id
  email
  firstName
  lastName
  numberOfOrders
  tags
}
fulfillments(first: 5) {
  id
  displayStatus
  deliveredAt
  inTransitAt
  createdAt
  updatedAt
}
refunds(first: 10) {
  id
  createdAt
  note
  totalRefundedSet { shopMoney { amount currencyCode } }
}
""".strip()


_ORDER_FIELDS_WITH_LINE_ITEMS = f"""
{_ORDER_FIELDS}
transactions(first: 50) {{
  id
  kind
  status
  gateway
  createdAt
  amountSet {{ shopMoney {{ amount currencyCode }} }}
  parentTransaction {{ id kind }}
}}
lineItems(first: 100) {{
  edges {{
    node {{
      id
      title
      quantity
      sku
      variant {{
        id
        title
      }}
      product {{
        id
        title
        tags
      }}
      originalUnitPriceSet {{ shopMoney {{ amount currencyCode }} }}
      discountedUnitPriceSet {{ shopMoney {{ amount currencyCode }} }}
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


_LIST_ORDERS_QUERY = f"""
query orders(
  $first: Int!,
  $after: String,
  $query: String,
  $sortKey: OrderSortKeys,
  $reverse: Boolean
) {{
  orders(
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
        {_ORDER_FIELDS}
      }}
    }}
  }}
}}
""".strip()


_GET_ORDER_QUERY = f"""
query order($id: ID!) {{
  order(id: $id) {{
    {_ORDER_FIELDS_WITH_LINE_ITEMS}
  }}
}}
""".strip()


_UPDATE_ORDER_MUTATION = f"""
mutation orderUpdate($input: OrderInput!) {{
  orderUpdate(input: $input) {{
    order {{
      {_ORDER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_TAGS_ADD_MUTATION = """
mutation tagsAdd($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    node {
      id
      ... on Order {
        tags
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_TAGS_REMOVE_MUTATION = """
mutation tagsRemove($id: ID!, $tags: [String!]!) {
  tagsRemove(id: $id, tags: $tags) {
    node {
      id
      ... on Order {
        tags
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_CLOSE_ORDER_MUTATION = """
mutation orderClose($input: OrderCloseInput!) {
  orderClose(input: $input) {
    order {
      id
      closed
      closedAt
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250

_VALID_SORT_KEYS = {
    "PROCESSED_AT", "TOTAL_PRICE", "UPDATED_AT", "CREATED_AT",
    "CUSTOMER_NAME", "FINANCIAL_STATUS", "FULFILLMENT_STATUS",
    "ID", "ORDER_NUMBER", "PO_NUMBER", "RELEVANCE",
}


class ShopifyOrdersAdapter(ShopifyBaseAdapter):
    name = "shopify_orders"
    capabilities = {
        Capability.SHOPIFY_LIST_ORDERS,
        Capability.SHOPIFY_FETCH_ORDERS,
        Capability.SHOPIFY_GET_ORDER,
        Capability.SHOPIFY_UPDATE_ORDER,
        Capability.SHOPIFY_TAG_ORDER,
        Capability.SHOPIFY_UNTAG_ORDER,
        Capability.SHOPIFY_CLOSE_ORDER,
    }
    # read for list/get; write for update/tag/untag/close.
    required_scopes = frozenset({"read_orders", "write_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability in (
            Capability.SHOPIFY_LIST_ORDERS,
            Capability.SHOPIFY_FETCH_ORDERS,
        ):
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_ORDER:
            return self._get(params)
        if capability == Capability.SHOPIFY_UPDATE_ORDER:
            return self._update(params)
        if capability == Capability.SHOPIFY_TAG_ORDER:
            return self._tag(params, add=True)
        if capability == Capability.SHOPIFY_UNTAG_ORDER:
            return self._tag(params, add=False)
        if capability == Capability.SHOPIFY_CLOSE_ORDER:
            return self._close(params)
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

        data = self._gql(_LIST_ORDERS_QUERY, variables)
        envelope = data.get("orders") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        orders = [
            self._normalise_order(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_ORDERS,
            data={
                "orders": orders,
                "count": len(orders),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        order_id = params.get("id") or params.get("order_id")
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the order) is required",
            )
        data = self._gql(_GET_ORDER_QUERY, {"id": order_id.strip()})
        node = data.get("order") or {}
        return self._success(
            Capability.SHOPIFY_GET_ORDER,
            data={
                "order": self._normalise_order_with_line_items(node),
                "found": bool(node),
            },
        )

    # ── Update (note / tags via OrderInput) ───────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        order_id = params.get("id") or params.get("order_id")
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the order) is required",
            )
        order_input: dict[str, Any] = {"id": order_id.strip()}

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    self.name, "'note' must be a string",
                )
            order_input["note"] = note

        email = params.get("email")
        if email is not None:
            if not isinstance(email, str):
                raise AdapterValidationError(
                    self.name, "'email' must be a string",
                )
            order_input["email"] = email

        tags = params.get("tags")
        if tags is not None:
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not isinstance(tags, list) or not all(
                isinstance(t, str) for t in tags
            ):
                raise AdapterValidationError(
                    self.name,
                    "'tags' must be a string (comma-separated) or list of strings",
                )
            order_input["tags"] = tags

        custom_attrs = params.get("custom_attributes") or params.get(
            "customAttributes"
        )
        if custom_attrs is not None:
            if not isinstance(custom_attrs, list):
                raise AdapterValidationError(
                    self.name,
                    "'custom_attributes' must be a list of {key, value} dicts",
                )
            normalised_attrs: list[dict[str, str]] = []
            for i, attr in enumerate(custom_attrs):
                if not isinstance(attr, dict):
                    raise AdapterValidationError(
                        self.name,
                        f"custom_attributes[{i}] must be a dict",
                    )
                key = attr.get("key")
                value = attr.get("value")
                if not isinstance(key, str) or not key.strip():
                    raise AdapterValidationError(
                        self.name,
                        f"custom_attributes[{i}] missing 'key'",
                    )
                normalised_attrs.append({
                    "key": key, "value": str(value) if value is not None else "",
                })
            order_input["customAttributes"] = normalised_attrs

        # If only id is set, nothing to update — fail-fast.
        if len(order_input) == 1:
            raise AdapterValidationError(
                self.name,
                "no updatable fields supplied (note, email, tags, "
                "custom_attributes)",
            )

        data = self._gql(_UPDATE_ORDER_MUTATION, {"input": order_input})
        self._check_user_errors(data, "orderUpdate")
        payload = data.get("orderUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_ORDER,
            data={
                "order": self._normalise_order(payload.get("order") or {}),
            },
        )

    # ── Tag / Untag ───────────────────────────────────────────────

    def _tag(self, params: dict[str, Any], add: bool) -> Any:
        order_id = params.get("id") or params.get("order_id")
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the order) is required",
            )
        raw_tags = params.get("tags")
        if isinstance(raw_tags, str):
            raw_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
        if not isinstance(raw_tags, list) or not raw_tags or not all(
            isinstance(t, str) for t in raw_tags
        ):
            raise AdapterValidationError(
                self.name,
                "'tags' must be a non-empty list of strings or "
                "comma-separated string",
            )
        mutation = _TAGS_ADD_MUTATION if add else _TAGS_REMOVE_MUTATION
        mutation_name = "tagsAdd" if add else "tagsRemove"
        capability = (
            Capability.SHOPIFY_TAG_ORDER if add
            else Capability.SHOPIFY_UNTAG_ORDER
        )
        data = self._gql(mutation, {
            "id": order_id.strip(),
            "tags": raw_tags,
        })
        self._check_user_errors(data, mutation_name)
        payload = data.get(mutation_name) or {}
        node = payload.get("node") or {}
        return self._success(
            capability,
            data={
                "id": node.get("id", "") or "",
                "tags": list(node.get("tags") or []),
            },
        )

    # ── Close ──────────────────────────────────────────────────────

    def _close(self, params: dict[str, Any]) -> Any:
        order_id = params.get("id") or params.get("order_id")
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the order) is required",
            )
        data = self._gql(_CLOSE_ORDER_MUTATION, {
            "input": {"id": order_id.strip()},
        })
        self._check_user_errors(data, "orderClose")
        payload = data.get("orderClose") or {}
        order = payload.get("order") or {}
        return self._success(
            Capability.SHOPIFY_CLOSE_ORDER,
            data={
                "id": order.get("id", "") or "",
                "closed": bool(order.get("closed", False)),
                "closed_at": order.get("closedAt", "") or "",
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
    def _normalise_order(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        total_amount, total_currency = cls._money(node.get("totalPriceSet"))
        subtotal_amount, _ = cls._money(node.get("subtotalPriceSet"))
        shipping_amount, _ = cls._money(node.get("totalShippingPriceSet"))
        tax_amount, _ = cls._money(node.get("totalTaxSet"))
        refunded_amount, _ = cls._money(node.get("totalRefundedSet"))
        customer = node.get("customer") or {}
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "email": node.get("email", "") or "",
            "phone": node.get("phone", "") or "",
            "note": node.get("note", "") or "",
            "tags": list(node.get("tags") or []),
            "financial_status": node.get("displayFinancialStatus", "") or "",
            "fulfillment_status": (
                node.get("displayFulfillmentStatus", "") or ""
            ),
            "processed_at": node.get("processedAt", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
            "cancelled_at": node.get("cancelledAt", "") or "",
            "closed_at": node.get("closedAt", "") or "",
            "currency_code": (
                node.get("currencyCode", "") or total_currency or ""
            ),
            "total_price": total_amount,
            "subtotal_price": subtotal_amount,
            "shipping_price": shipping_amount,
            "tax_price": tax_amount,
            "refunded_price": refunded_amount,
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
            # W962-10 bugfix: emit customer.tags so revenue
            # attribution + tag-based segmentation can read
            # them from the LIST orders path (was missing
            # before; attribution undercounted).
            "customer_tags": list(
                customer.get("tags") or []
                if isinstance(customer, dict) else []
            ),
            # W962-2 + W962-3 bugfix: emit fulfillments +
            # refunds so shipping_alert + order_followup
            # discoverers can operate on LIST orders. Pre-fix
            # they always returned empty / mis-tagged.
            "fulfillments": [
                cls._normalise_fulfillment(f)
                for f in (node.get("fulfillments") or [])
                if isinstance(f, dict)
            ],
            "refunds": [
                cls._normalise_refund(r)
                for r in (node.get("refunds") or [])
                if isinstance(r, dict)
            ],
        }

    @classmethod
    def _normalise_fulfillment(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": node.get("id", "") or "",
            "display_status": node.get("displayStatus", "") or "",
            "delivered_at": node.get("deliveredAt", "") or "",
            "in_transit_at": node.get("inTransitAt", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }

    @classmethod
    def _normalise_refund(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        amt, cur = cls._money(node.get("totalRefundedSet"))
        return {
            "id": node.get("id", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "note": node.get("note", "") or "",
            "total_refunded": amt,
            "currency_code": cur,
        }

    @classmethod
    def _normalise_transaction(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        # W962-1: emit transactions for refund_applier
        amt, cur = cls._money(node.get("amountSet"))
        parent = node.get("parentTransaction") or {}
        return {
            "id": node.get("id", "") or "",
            "kind": node.get("kind", "") or "",
            "status": node.get("status", "") or "",
            "gateway": node.get("gateway", "") or "",
            "created_at": node.get("createdAt", "") or "",
            "amount": amt,
            "currency_code": cur,
            "parent_transaction_id": (
                parent.get("id", "") if isinstance(parent, dict)
                else ""
            ) or "",
            "parent_transaction_kind": (
                parent.get("kind", "") if isinstance(parent, dict)
                else ""
            ) or "",
        }

    @classmethod
    def _normalise_order_with_line_items(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        base = cls._normalise_order(node)
        if not base:
            return {}
        # W962-1 bugfix: emit transactions so the refund
        # applier can find the parent_transaction it needs.
        # Pre-fix every refund silently skipped with
        # `no_parent_transaction` because this field was
        # never normalised.
        base["transactions"] = [
            cls._normalise_transaction(t)
            for t in (node.get("transactions") or [])
            if isinstance(t, dict)
        ]
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
        discounted_amount, _ = cls._money(node.get("discountedUnitPriceSet"))
        variant = node.get("variant") or {}
        product = node.get("product") or {}
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "quantity": int(node.get("quantity") or 0),
            "sku": node.get("sku", "") or "",
            "variant_id": (
                variant.get("id", "")
                if isinstance(variant, dict) else ""
            ) or "",
            "variant_title": (
                variant.get("title", "")
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
            # W962-10: product.tags so revenue_attribution
            # can join line-items to product-tag-based
            # campaigns. Pre-fix this field wasn't queried.
            "product_tags": list(
                product.get("tags") or []
                if isinstance(product, dict) else []
            ),
            "original_unit_price": original_amount,
            "discounted_unit_price": discounted_amount,
        }
