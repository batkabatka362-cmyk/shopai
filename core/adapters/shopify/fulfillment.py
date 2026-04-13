"""ShopifyFulfillmentAdapter — order fulfillment + tracking.

Wraps Shopify's modern fulfillment API:

  * ``fulfillmentOrders`` query — returns the
    ``FulfillmentOrder`` records for a given order. Shopify
    splits one customer-facing order into multiple
    fulfillment orders (one per location), and the
    ``fulfillmentCreate`` mutation operates on them, NOT on
    the original order. Most callers don't realise this — the
    adapter hides the indirection so the brain can just say
    "fulfill order #1234".
  * ``fulfillmentCreate`` mutation — actually creates the
    fulfillment with optional tracking info.
  * ``fulfillmentCancel`` mutation — cancels an outbound
    fulfillment if it hasn't been picked up yet.

Replaces the deleted ``execution/fulfillment/auto_fulfill.py``
hardcoded ETA table with a real Shopify-side fulfillment that
returns whatever ETA the carrier integration emits.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterError, AdapterValidationError
from ._base import ShopifyBaseAdapter


_FULFILLMENT_ORDERS_QUERY = """
query FulfillmentOrdersForOrder($id: ID!) {
  order(id: $id) {
    id
    name
    fulfillmentOrders(first: 10) {
      edges {
        node {
          id
          status
          requestStatus
          assignedLocation {
            location {
              id
              name
            }
          }
          lineItems(first: 50) {
            edges {
              node {
                id
                remainingQuantity
                totalQuantity
                lineItem {
                  id
                  title
                  sku
                }
              }
            }
          }
        }
      }
    }
  }
}
""".strip()


_FULFILLMENT_CREATE_MUTATION = """
mutation FulfillmentCreate($fulfillment: FulfillmentInput!) {
  fulfillmentCreate(fulfillment: $fulfillment) {
    fulfillment {
      id
      status
      createdAt
      trackingInfo {
        company
        number
        url
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_FULFILLMENT_CANCEL_MUTATION = """
mutation FulfillmentCancel($id: ID!) {
  fulfillmentCancel(id: $id) {
    fulfillment {
      id
      status
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyFulfillmentAdapter(ShopifyBaseAdapter):
    name = "shopify_fulfillment"
    capabilities = {Capability.SHOPIFY_CREATE_FULFILLMENT}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_CREATE_FULFILLMENT:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        # Two operating modes — the action key tells us which
        # one. Default is "fulfill". Cancel is the inverse.
        action = str(params.get("action") or "fulfill").lower()
        if action == "cancel":
            return self._cancel(params)
        return self._fulfill(params)

    # ── Create fulfillment ────────────────────────────────────

    def _fulfill(self, params: dict[str, Any]) -> Any:
        """Create one or more fulfillments for the given order.

        ``params``:

            {
                "order_id": "gid://shopify/Order/12345" | "12345",
                "tracking": {
                    "company": "USPS",
                    "number": "9400111899223197428490",
                    "url":    "https://tools.usps.com/...",
                },
                "notify_customer": True,
                # Optional explicit line filter — when omitted
                # the adapter fulfils every remaining line item
                # in every fulfillmentOrder for this order.
                "fulfillment_order_line_items": [
                    {"id": "gid://...", "quantity": 1},
                    ...
                ],
            }
        """
        order_id = params.get("order_id") or params.get("id")
        if not order_id:
            raise AdapterValidationError(
                self.name, "'order_id' is required",
            )
        gid = self._to_order_gid(order_id)

        # Step 1: discover the FulfillmentOrders for this order.
        order_data = self._gql(_FULFILLMENT_ORDERS_QUERY, {"id": gid})
        order = order_data.get("order") or {}
        if not order:
            raise AdapterError(
                self.name, f"order {gid!r} not found",
            )

        fo_edges = ((order.get("fulfillmentOrders") or {}).get("edges") or [])
        if not fo_edges:
            raise AdapterError(
                self.name, "no fulfillment orders for this order",
            )

        # Build the line-items-by-fulfillment-order list. The
        # caller can pass an explicit filter; otherwise we fulfil
        # every remaining line item in every fulfillment order
        # whose ``status`` is "OPEN".
        explicit_lines = params.get("fulfillment_order_line_items")
        line_items_by_fo: list[dict[str, Any]] = []

        for edge in fo_edges:
            node = edge.get("node") or {}
            fo_id = node.get("id")
            status = str(node.get("status", "") or "").upper()
            if not fo_id or status != "OPEN":
                continue

            if explicit_lines is not None:
                fo_line_items = explicit_lines
            else:
                fo_line_items = []
                for li_edge in (
                    (node.get("lineItems") or {}).get("edges") or []
                ):
                    li_node = li_edge.get("node") or {}
                    remaining = int(li_node.get("remainingQuantity", 0) or 0)
                    if remaining <= 0:
                        continue
                    fo_line_items.append({
                        "id": li_node.get("id"),
                        "quantity": remaining,
                    })

            if fo_line_items:
                line_items_by_fo.append({
                    "fulfillmentOrderId": fo_id,
                    "fulfillmentOrderLineItems": fo_line_items,
                })

        if not line_items_by_fo:
            raise AdapterError(
                self.name,
                "nothing left to fulfil — every line item is already shipped",
            )

        fulfillment_input: dict[str, Any] = {
            "lineItemsByFulfillmentOrder": line_items_by_fo,
            "notifyCustomer": bool(params.get("notify_customer", True)),
        }

        tracking = params.get("tracking")
        if isinstance(tracking, dict):
            tracking_info = {}
            if tracking.get("company"):
                tracking_info["company"] = tracking["company"]
            if tracking.get("number"):
                tracking_info["number"] = tracking["number"]
            if tracking.get("url"):
                tracking_info["url"] = tracking["url"]
            if tracking_info:
                fulfillment_input["trackingInfo"] = tracking_info

        # Step 2: create the fulfillment
        result = self._gql(
            _FULFILLMENT_CREATE_MUTATION,
            {"fulfillment": fulfillment_input},
        )
        self._check_user_errors(result, "fulfillmentCreate")

        payload = (result.get("fulfillmentCreate") or {})
        fulfillment = payload.get("fulfillment") or {}

        return self._success(
            Capability.SHOPIFY_CREATE_FULFILLMENT,
            data={
                "order_id": gid,
                "order_name": order.get("name", ""),
                "fulfillment_id": fulfillment.get("id", ""),
                "status": fulfillment.get("status", ""),
                "created_at": fulfillment.get("createdAt", ""),
                "tracking": fulfillment.get("trackingInfo", []),
                "fulfillment_orders_used": len(line_items_by_fo),
            },
        )

    # ── Cancel fulfillment ────────────────────────────────────

    def _cancel(self, params: dict[str, Any]) -> Any:
        fulfillment_id = params.get("fulfillment_id")
        if not fulfillment_id:
            raise AdapterValidationError(
                self.name, "'fulfillment_id' is required for cancel",
            )

        result = self._gql(
            _FULFILLMENT_CANCEL_MUTATION,
            {"id": fulfillment_id},
        )
        self._check_user_errors(result, "fulfillmentCancel")

        payload = (result.get("fulfillmentCancel") or {})
        fulfillment = payload.get("fulfillment") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_FULFILLMENT,
            data={
                "fulfillment_id": fulfillment.get("id", ""),
                "status": fulfillment.get("status", ""),
                "action": "cancelled",
            },
        )

    # ── Helpers ────────────────────────────────────────────────

    @staticmethod
    def _to_order_gid(order_id: Any) -> str:
        s = str(order_id)
        if s.startswith("gid://"):
            return s
        return f"gid://shopify/Order/{s}"
