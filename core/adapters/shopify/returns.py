"""ShopifyReturnsAdapter — query and triage returns / refund requests.

ShopAI's churn engine and refund analytics need to read which orders
got returned, what the customer's reason was, and how often it happens
per customer. The merchant's manual return-approval workflow is also
slow when volumes climb — for trusted customers ShopAI can approve
pending returns automatically (with a guardrail that escalates if the
return rate spikes).

Two read paths and two write paths:

  * ``SHOPIFY_LIST_RETURNS``   — page through returns shop-wide,
    optionally filtered by status / order. Drives the refund-analytics
    dashboard and the churn engine's "customer X has Y returns in
    rolling 90d" feature.
  * ``SHOPIFY_GET_RETURN``     — fetch one return with its line items
    and reasons. Used for individual decision support.
  * ``SHOPIFY_APPROVE_RETURN`` — approve a pending return via
    ``returnApproveRequest`` (auto-approval for trusted customers).
  * ``SHOPIFY_DECLINE_RETURN`` — decline a pending return via
    ``returnDeclineRequest``.

Refund issuance is intentionally NOT in this adapter — refunds are a
financial operation with its own audit trail and policy implications,
and conflating them with the return record makes both flows harder to
reason about. A dedicated ``ShopifyRefundsAdapter`` will land later
when the refund engine is wired in.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Common fields shared between list and single-fetch so the wire
# format stays consistent for the normaliser.
_RETURN_NODE_FIELDS = """
id
name
status
totalQuantity
order {
  id
  name
}
returnLineItems(first: 50) {
  edges {
    node {
      id
      quantity
      returnReason
      returnReasonNote
      ... on ReturnLineItem {
        fulfillmentLineItem {
          lineItem {
            id
            title
            variantTitle
            sku
          }
        }
      }
    }
  }
}
""".strip()


# NOTE: Shopify's QueryRoot does NOT expose a ``returns`` connection
# (caught live during smoke test as "Field 'returns' doesn't exist on
# type 'QueryRoot'"; ``ReturnSortKeys`` enum likewise isn't defined at
# the top level). Returns are only traversable through the order they
# belong to. The list query below paginates ORDERS filtered by return
# status and flattens the per-order returns connection into a single
# list — so callers still get a flat "all returns matching X" view
# without having to know about the underlying orders-based traversal.
_LIST_RETURNS_QUERY = f"""
query orderReturns($first: Int!, $after: String, $query: String) {{
  orders(first: $first, after: $after, query: $query) {{
    pageInfo {{
      hasNextPage
      endCursor
    }}
    edges {{
      node {{
        returns(first: 10) {{
          edges {{
            node {{
              {_RETURN_NODE_FIELDS}
            }}
          }}
        }}
      }}
    }}
  }}
}}
""".strip()


_GET_RETURN_QUERY = f"""
query getReturn($id: ID!) {{
  return(id: $id) {{
    {_RETURN_NODE_FIELDS}
  }}
}}
""".strip()


_APPROVE_RETURN_MUTATION = """
mutation returnApproveRequest($input: ReturnApproveRequestInput!) {
  returnApproveRequest(input: $input) {
    return {
      id
      status
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


# NOTE: ``Return.declineReason`` does NOT exist on the Return type in
# the current schema (caught live as 'Field declineReason doesn't
# exist on type Return'). The mutation accepts a ``declineReason``
# input but doesn't echo it back. Callers that need to remember why
# they declined should track it on their side or write it as a
# metafield on the order.
_DECLINE_RETURN_MUTATION = """
mutation returnDeclineRequest($input: ReturnDeclineRequestInput!) {
  returnDeclineRequest(input: $input) {
    return {
      id
      status
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

# Aliases for the ReturnDeclineReason enum. Engines may pass natural
# words; we map to the canonical UPPER_SNAKE values Shopify expects.
_DECLINE_REASONS = {
    "final_sale": "FINAL_SALE",
    "return_period_ended": "RETURN_PERIOD_ENDED",
    "expired": "RETURN_PERIOD_ENDED",
    "other": "OTHER",
}


class ShopifyReturnsAdapter(ShopifyBaseAdapter):
    name = "shopify_returns"
    capabilities = {
        Capability.SHOPIFY_LIST_RETURNS,
        Capability.SHOPIFY_GET_RETURN,
        Capability.SHOPIFY_APPROVE_RETURN,
        Capability.SHOPIFY_DECLINE_RETURN,
    }
    # Returns ride on the orders scope plus return-management.
    required_scopes = frozenset({
        "read_returns", "write_returns",
        "read_orders",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_RETURNS:
            return self._list_returns(params)
        if capability == Capability.SHOPIFY_GET_RETURN:
            return self._get_return(params)
        if capability == Capability.SHOPIFY_APPROVE_RETURN:
            return self._approve_return(params)
        if capability == Capability.SHOPIFY_DECLINE_RETURN:
            return self._decline_return(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ────────────────────────────────────────────────────────

    def _list_returns(self, params: dict[str, Any]) -> Any:
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                "shopify_returns", "'cursor' must be a string or None",
            )
        query = params.get("query")
        if query is not None and not isinstance(query, str):
            raise AdapterValidationError(
                "shopify_returns", "'query' must be a string or None",
            )
        # Default the order-side filter to orders that actually have a
        # return record. Without it we'd page through every order in
        # the shop just to find the few with returns — wasteful for
        # the analytics dashboard's main use case.
        if query is None:
            query = "return_status:RETURN_REQUESTED OR return_status:IN_PROGRESS OR return_status:RETURNED"

        data = self._gql(_LIST_RETURNS_QUERY, {
            "first": limit,
            "after": cursor,
            "query": query,
        })
        envelope = data.get("orders") or {}
        page_info = envelope.get("pageInfo") or {}
        order_edges = envelope.get("edges") or []
        returns: list[dict[str, Any]] = []
        for order_edge in order_edges:
            if not isinstance(order_edge, dict):
                continue
            order_node = order_edge.get("node") or {}
            ret_envelope = order_node.get("returns") or {}
            for ret_edge in ret_envelope.get("edges") or []:
                if not isinstance(ret_edge, dict):
                    continue
                ret_node = ret_edge.get("node") or {}
                # The ``order`` field on a Return resolves at the
                # return level too, so the normaliser still works
                # even though we navigated via the order.
                returns.append(self._normalise_return(ret_node))

        return self._success(
            Capability.SHOPIFY_LIST_RETURNS,
            data={
                "returns": returns,
                "count": len(returns),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
            },
        )

    # ── Get one ────────────────────────────────────────────────────

    def _get_return(self, params: dict[str, Any]) -> Any:
        return_id = params.get("id") or params.get("return_id")
        if not isinstance(return_id, str) or not return_id.strip():
            raise AdapterValidationError(
                "shopify_returns",
                "'id' (Shopify GID for the return) is required",
            )
        data = self._gql(_GET_RETURN_QUERY, {"id": return_id.strip()})
        node = data.get("return")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_RETURN,
                data={"return": None, "found": False},
            )
        return self._success(
            Capability.SHOPIFY_GET_RETURN,
            data={"return": self._normalise_return(node), "found": True},
        )

    # ── Approve ────────────────────────────────────────────────────

    def _approve_return(self, params: dict[str, Any]) -> Any:
        return_id = params.get("id") or params.get("return_id")
        if not isinstance(return_id, str) or not return_id.strip():
            raise AdapterValidationError(
                "shopify_returns",
                "'id' (Shopify GID for the return) is required",
            )
        notify_customer = bool(params.get("notify_customer", True))
        data = self._gql(_APPROVE_RETURN_MUTATION, {
            "input": {
                "id": return_id.strip(),
                "notifyCustomer": notify_customer,
            },
        })
        self._check_user_errors(data, "returnApproveRequest")
        payload = data.get("returnApproveRequest") or {}
        ret = payload.get("return") or {}
        return self._success(
            Capability.SHOPIFY_APPROVE_RETURN,
            data={
                "id": ret.get("id", "") or "",
                "status": ret.get("status", "") or "",
            },
        )

    # ── Decline ────────────────────────────────────────────────────

    def _decline_return(self, params: dict[str, Any]) -> Any:
        return_id = params.get("id") or params.get("return_id")
        if not isinstance(return_id, str) or not return_id.strip():
            raise AdapterValidationError(
                "shopify_returns",
                "'id' (Shopify GID for the return) is required",
            )
        reason_raw = params.get("decline_reason") or params.get("reason") or "OTHER"
        if not isinstance(reason_raw, str):
            raise AdapterValidationError(
                "shopify_returns",
                "'decline_reason' must be a string",
            )
        reason = _DECLINE_REASONS.get(
            reason_raw.lower(), reason_raw.upper(),
        )
        if reason not in {"FINAL_SALE", "RETURN_PERIOD_ENDED", "OTHER"}:
            raise AdapterValidationError(
                "shopify_returns",
                f"'decline_reason' must be one of FINAL_SALE / "
                f"RETURN_PERIOD_ENDED / OTHER, got {reason_raw!r}",
            )
        data = self._gql(_DECLINE_RETURN_MUTATION, {
            "input": {
                "id": return_id.strip(),
                "declineReason": reason,
            },
        })
        self._check_user_errors(data, "returnDeclineRequest")
        payload = data.get("returnDeclineRequest") or {}
        ret = payload.get("return") or {}
        return self._success(
            Capability.SHOPIFY_DECLINE_RETURN,
            data={
                "id": ret.get("id", "") or "",
                "status": ret.get("status", "") or "",
                # Echo the reason we sent so callers don't have to
                # remember it; the API doesn't surface it on the
                # return object.
                "decline_reason": reason,
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_return(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        order = node.get("order") or {}
        line_items_raw = (
            (node.get("returnLineItems") or {}).get("edges") or []
        )
        line_items: list[dict[str, Any]] = []
        for edge in line_items_raw:
            if not isinstance(edge, dict):
                continue
            li_node = edge.get("node") or {}
            ff_li = li_node.get("fulfillmentLineItem") or {}
            line = ff_li.get("lineItem") if isinstance(ff_li, dict) else None
            if not isinstance(line, dict):
                line = {}
            line_items.append({
                "id": li_node.get("id", "") or "",
                "quantity": int(li_node.get("quantity", 0) or 0),
                "reason": li_node.get("returnReason", "") or "",
                "reason_note": li_node.get("returnReasonNote", "") or "",
                "product_title": line.get("title", "") or "",
                "variant_title": line.get("variantTitle", "") or "",
                "sku": line.get("sku", "") or "",
            })
        return {
            "id": node.get("id", "") or "",
            "name": node.get("name", "") or "",
            "status": node.get("status", "") or "",
            "total_quantity": int(node.get("totalQuantity", 0) or 0),
            "order_id": order.get("id", "") or "",
            "order_name": order.get("name", "") or "",
            "line_items": line_items,
        }
