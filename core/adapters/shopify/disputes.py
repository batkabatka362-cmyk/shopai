"""ShopifyDisputesAdapter — payment dispute / chargeback reads.

Disputes are Shopify Payments chargebacks / inquiries — when a
customer's bank or credit-card issuer reverses a payment claiming
fraud, "didn't receive", or non-recognition. They cost money (fees +
refund) and tank the merchant's risk score.

ShopAI's risk engine ingests disputes to:

  * Auto-tag the original order ("disputed:fraud") for downstream
    rules.
  * Auto-tag the customer ("disputed_x_times") so segmentation /
    marketing engines avoid re-targeting fraudulent buyers.
  * Surface a daily dispute digest in the operator dashboard.

The submit-evidence flow is intentionally NOT wired here — that's a
high-stakes write that the merchant should approve manually, not
something an autonomous AI should drive.

Capabilities:

  * ``SHOPIFY_LIST_DISPUTES`` — paginated list with optional filter.
  * ``SHOPIFY_GET_DISPUTE``   — single dispute with order link.

Pattern E note: ``shopifyPaymentsDisputes`` is gated by Shopify
Payments being enabled on the shop (and the matching scope
``read_shopify_payments_disputes``). Stores using non-Shopify
gateways (Stripe / PayPal) won't surface disputes via this path.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_DISPUTE_FIELDS = """
id
status
reasonDetails {
  reason
  networkReasonCode
}
amount {
  amount
  currencyCode
}
type
initiatedAt
evidenceDueBy
evidenceSentOn
finalizedOn
order {
  id
  name
}
""".strip()


_LIST_DISPUTES_QUERY = f"""
query shopifyPaymentsDisputes($first: Int!, $after: String) {{
  shopifyPaymentsAccount {{
    disputes(first: $first, after: $after) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      edges {{
        node {{
          {_DISPUTE_FIELDS}
        }}
      }}
    }}
  }}
}}
""".strip()


_GET_DISPUTE_QUERY = f"""
query dispute($id: ID!) {{
  node(id: $id) {{
    ... on ShopifyPaymentsDispute {{
      {_DISPUTE_FIELDS}
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyDisputesAdapter(ShopifyBaseAdapter):
    name = "shopify_disputes"
    capabilities = {
        Capability.SHOPIFY_LIST_DISPUTES,
        Capability.SHOPIFY_GET_DISPUTE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_DISPUTES:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_DISPUTE:
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

        # Pattern D: shopifyPaymentsAccount.disputes does NOT accept
        # sortKey / query / reverse arguments (unlike most connections).
        # Engines that need ordering / filtering have to do it client-
        # side after pagination.
        data = self._gql(_LIST_DISPUTES_QUERY, variables)
        # The disputes connection lives one level inside
        # shopifyPaymentsAccount — flatten so engines don't have to
        # know the schema shape. If the shop isn't on Shopify
        # Payments, shopifyPaymentsAccount is null.
        account = data.get("shopifyPaymentsAccount") or {}
        envelope = account.get("disputes") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        disputes = [
            self._normalise_dispute(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_DISPUTES,
            data={
                "disputes": disputes,
                "count": len(disputes),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
                "shop_uses_shopify_payments": bool(account),
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        dispute_id = params.get("id") or params.get("dispute_id")
        if not isinstance(dispute_id, str) or not dispute_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the dispute) is required",
            )
        data = self._gql(_GET_DISPUTE_QUERY, {"id": dispute_id.strip()})
        node = data.get("node") or {}
        return self._success(
            Capability.SHOPIFY_GET_DISPUTE,
            data={
                "dispute": self._normalise_dispute(node),
                "found": bool(node),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_dispute(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        amount = node.get("amount") or {}
        order = node.get("order") or {}
        reason_details = node.get("reasonDetails") or {}
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "type": node.get("type", "") or "",
            "reason": (
                reason_details.get("reason", "")
                if isinstance(reason_details, dict) else ""
            ) or "",
            "network_reason_code": (
                reason_details.get("networkReasonCode", "")
                if isinstance(reason_details, dict) else ""
            ) or "",
            "amount": (
                amount.get("amount", "") if isinstance(amount, dict) else ""
            ) or "",
            "currency_code": (
                amount.get("currencyCode", "")
                if isinstance(amount, dict) else ""
            ) or "",
            "initiated_at": node.get("initiatedAt", "") or "",
            "evidence_due_by": node.get("evidenceDueBy", "") or "",
            "evidence_sent_on": node.get("evidenceSentOn", "") or "",
            "finalized_on": node.get("finalizedOn", "") or "",
            "order_id": (
                order.get("id", "") if isinstance(order, dict) else ""
            ) or "",
            "order_name": (
                order.get("name", "") if isinstance(order, dict) else ""
            ) or "",
        }
