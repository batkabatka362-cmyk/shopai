"""ShopifyOrdersAdapter — paginated order read.

Fills the ``SHOPIFY_FETCH_ORDERS`` gap in the adapter catalog
(Option D). The autonomous controller needs an abstract way to
pull orders for fulfillment sweeps, refund triage, subscription
dunning, and analytics — and previously nothing implemented that
capability, so ``SmartRouter.route(SHOPIFY_FETCH_ORDERS)`` raised
``NoAdapterAvailable`` and the engine layer fell back to the
legacy ``shopify_graphql`` client with none of the retry /
breaker / cost attribution that the adapter layer provides.

This adapter is READ-ONLY. All mutating order actions (refund,
capture, cancel) live in the payment adapters or in a future
``ShopifyOrderMutateAdapter``.

Params shape::

    {
        "status": "open" | "closed" | "cancelled" | "any",  # default "any"
        "query":  "tag:vip updated_at:>2026-01-01",  # optional raw filter
        "first":  50,          # page size (max 250, Shopify cap)
        "after":  "cursor...", # Shopify page cursor
        "include_line_items": True,  # default False — cheap pagination
    }

Returns::

    {
        "orders":  [...],          # normalised order dicts
        "page_info": {"has_next_page": bool, "end_cursor": str},
        "count":    int,
    }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_ORDERS_QUERY = """
query FetchOrders(
    $first: Int!,
    $after: String,
    $query: String,
    $includeLineItems: Boolean!
) {
  orders(first: $first, after: $after, query: $query, sortKey: UPDATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges {
      cursor
      node {
        id
        name
        createdAt
        updatedAt
        processedAt
        displayFinancialStatus
        displayFulfillmentStatus
        cancelledAt
        cancelReason
        currentTotalPriceSet { shopMoney { amount currencyCode } }
        totalDiscountsSet    { shopMoney { amount currencyCode } }
        totalTaxSet          { shopMoney { amount currencyCode } }
        customer { id displayName email }
        email
        tags
        note
        lineItems(first: 50) @include(if: $includeLineItems) {
          edges {
            node {
              id
              sku
              name
              quantity
              currentQuantity
              variant { id sku }
              originalTotalSet { shopMoney { amount currencyCode } }
            }
          }
        }
      }
    }
  }
}
""".strip()


# Shopify's ``status`` field accepts specific literals for the query
# filter DSL. Anything else must be phrased as a raw ``query`` string.
_STATUS_FILTERS = {
    "any": "",
    "open": "status:open",
    "closed": "status:closed",
    "cancelled": "status:cancelled",
}


class ShopifyOrdersAdapter(ShopifyBaseAdapter):
    """Read paginated orders from Shopify Admin."""

    name = "shopify_orders"
    capabilities = {Capability.SHOPIFY_FETCH_ORDERS}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_FETCH_ORDERS:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        # Normalise + validate params.
        status = str(params.get("status") or "any").lower()
        if status not in _STATUS_FILTERS:
            raise AdapterValidationError(
                self.name,
                f"status must be one of {sorted(_STATUS_FILTERS)}",
            )
        extra_query = str(params.get("query") or "").strip()
        raw_filter = " ".join(
            p for p in (_STATUS_FILTERS[status], extra_query) if p
        ) or None

        try:
            first = int(params.get("first", 50))
        except (TypeError, ValueError):
            raise AdapterValidationError(
                self.name, "'first' must be an integer",
            )
        if first <= 0 or first > 250:
            raise AdapterValidationError(
                self.name, "'first' must be in 1..250 (Shopify cap)",
            )

        after = params.get("after")
        include_line_items = bool(params.get("include_line_items", False))

        variables = {
            "first": first,
            "after": after or None,
            "query": raw_filter,
            "includeLineItems": include_line_items,
        }

        data = self._gql(_ORDERS_QUERY, variables)
        orders_block = data.get("orders") or {}
        edges = orders_block.get("edges") or []
        page_info = orders_block.get("pageInfo") or {}

        out_orders: list[dict[str, Any]] = []
        for edge in edges:
            node = edge.get("node") or {}
            money = (node.get("currentTotalPriceSet") or {}).get(
                "shopMoney"
            ) or {}
            customer = node.get("customer") or {}
            row: dict[str, Any] = {
                "id": node.get("id", ""),
                "name": node.get("name", ""),
                "created_at": node.get("createdAt", ""),
                "updated_at": node.get("updatedAt", ""),
                "processed_at": node.get("processedAt", ""),
                "cancelled_at": node.get("cancelledAt", ""),
                "cancel_reason": node.get("cancelReason", ""),
                "financial_status": (
                    node.get("displayFinancialStatus", "") or ""
                ).lower(),
                "fulfillment_status": (
                    node.get("displayFulfillmentStatus", "") or ""
                ).lower(),
                "total_amount": money.get("amount", "0"),
                "currency": money.get("currencyCode", ""),
                "customer_id": customer.get("id", ""),
                "customer_name": customer.get("displayName", ""),
                "email": node.get("email") or customer.get("email", ""),
                "tags": list(node.get("tags") or []),
                "note": node.get("note", "") or "",
                "cursor": edge.get("cursor", ""),
            }
            if include_line_items:
                li_edges = (
                    (node.get("lineItems") or {}).get("edges") or []
                )
                row["line_items"] = [
                    {
                        "id": (li.get("node") or {}).get("id", ""),
                        "sku": (
                            (li.get("node") or {}).get("sku")
                            or (((li.get("node") or {}).get("variant")
                                 or {}).get("sku", ""))
                        ),
                        "name": (li.get("node") or {}).get("name", ""),
                        "quantity": int(
                            (li.get("node") or {}).get("quantity", 0) or 0
                        ),
                        "current_quantity": int(
                            (li.get("node") or {}).get("currentQuantity", 0)
                            or 0
                        ),
                    }
                    for li in li_edges
                ]
            out_orders.append(row)

        return self._success(
            Capability.SHOPIFY_FETCH_ORDERS,
            data={
                "orders": out_orders,
                "count": len(out_orders),
                "page_info": {
                    "has_next_page": bool(page_info.get("hasNextPage")),
                    "end_cursor": page_info.get("endCursor", "") or "",
                },
            },
        )
