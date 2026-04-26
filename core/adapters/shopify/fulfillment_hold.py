"""ShopifyFulfillmentHoldAdapter — fraud-pause fulfillment orders.

Companion to ``fulfillment.py`` (creates fulfillments) and
``fulfillment_events.py`` (logs shipping events). The hold flow lets
the brain layer FREEZE a fulfillment order before it ships when a
risk signal arrives — chargeback history, address mismatch, AI fraud
score above threshold, or a manual operator escalation.

ShopAI's risk + fulfillment engines use these to:

  * Auto-hold orders on a high AI fraud score so a human can review
    before the package ships.
  * Hold all open fulfillment orders for a customer who just
    triggered a chargeback dispute.
  * Release the hold when the review clears (or if the customer
    provides additional verification).

Capabilities:

  * ``SHOPIFY_HOLD_FULFILLMENT_ORDER``         — pause a specific
    fulfillment order with a reason + optional message.
  * ``SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD`` — clear the hold so
    the order can ship.

Friendly call shape::

    {"fulfillment_order_id": "gid://shopify/FulfillmentOrder/123",
     "reason":               "OTHER",
     "reason_notes":         "AI fraud score 0.92 — manual review",
     "notify_merchant":      True,
     "external_id":          "shopai-hold-2026-04-26-001"}

Pattern A: ``fulfillmentOrderHold`` takes the fulfillment-order GID
at field level + a ``fulfillmentHold`` Input. Same convention as
fulfillmentEventCreate (Phase 13.5).

Pattern E note: gated by ``write_merchant_managed_fulfillment_orders``
or ``write_third_party_fulfillment_orders`` scope (depending on who
owns the FO). Smart router skips when neither is granted.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_FULFILLMENT_ORDER_FIELDS = """
id
status
requestStatus
fulfillmentHolds {
  id
  reason
  reasonNotes
  heldByApp {
    id
  }
}
""".strip()


_HOLD_FULFILLMENT_ORDER_MUTATION = f"""
mutation fulfillmentOrderHold(
  $id: ID!,
  $fulfillmentHold: FulfillmentOrderHoldInput!
) {{
  fulfillmentOrderHold(id: $id, fulfillmentHold: $fulfillmentHold) {{
    fulfillmentOrder {{
      {_FULFILLMENT_ORDER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_RELEASE_FULFILLMENT_ORDER_HOLD_MUTATION = f"""
mutation fulfillmentOrderReleaseHold($id: ID!, $externalId: String) {{
  fulfillmentOrderReleaseHold(id: $id, externalId: $externalId) {{
    fulfillmentOrder {{
      {_FULFILLMENT_ORDER_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_VALID_REASONS = {
    "AWAITING_PAYMENT",
    "HIGH_RISK_OF_FRAUD",
    "INCORRECT_ADDRESS",
    "INVENTORY_OUT_OF_STOCK",
    "OTHER",
    "UNKNOWN_DELIVERY_DATE",
    "ONLINE_STORE_POST_PURCHASE_CROSS_SELL",
    "AWAITING_RETURN_ITEMS",
    "AWAITING_PAYMENT_CONFIRMATION",
}


class ShopifyFulfillmentHoldAdapter(ShopifyBaseAdapter):
    name = "shopify_fulfillment_hold"
    capabilities = {
        Capability.SHOPIFY_HOLD_FULFILLMENT_ORDER,
        Capability.SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_HOLD_FULFILLMENT_ORDER:
            return self._hold(params)
        if capability == Capability.SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD:
            return self._release(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Hold ───────────────────────────────────────────────────────

    def _hold(self, params: dict[str, Any]) -> Any:
        fo_id = params.get("fulfillment_order_id") or params.get(
            "fulfillmentOrderId"
        )
        if not isinstance(fo_id, str) or not fo_id.strip():
            raise AdapterValidationError(
                self.name,
                "'fulfillment_order_id' (Shopify GID) is required",
            )

        hold_input = self._build_hold_input(params)
        data = self._gql(_HOLD_FULFILLMENT_ORDER_MUTATION, {
            "id": fo_id.strip(),
            "fulfillmentHold": hold_input,
        })
        self._check_user_errors(data, "fulfillmentOrderHold")
        payload = data.get("fulfillmentOrderHold") or {}
        return self._success(
            Capability.SHOPIFY_HOLD_FULFILLMENT_ORDER,
            data={
                "fulfillment_order": self._normalise_fulfillment_order(
                    payload.get("fulfillmentOrder") or {},
                ),
            },
        )

    # ── Release ───────────────────────────────────────────────────

    def _release(self, params: dict[str, Any]) -> Any:
        fo_id = params.get("fulfillment_order_id") or params.get(
            "fulfillmentOrderId"
        )
        if not isinstance(fo_id, str) or not fo_id.strip():
            raise AdapterValidationError(
                self.name,
                "'fulfillment_order_id' (Shopify GID) is required",
            )

        variables: dict[str, Any] = {"id": fo_id.strip()}

        external_id = params.get("external_id") or params.get("externalId")
        if external_id is not None:
            if not isinstance(external_id, str):
                raise AdapterValidationError(
                    self.name, "'external_id' must be a string",
                )
            variables["externalId"] = external_id.strip()

        data = self._gql(
            _RELEASE_FULFILLMENT_ORDER_HOLD_MUTATION, variables,
        )
        self._check_user_errors(data, "fulfillmentOrderReleaseHold")
        payload = data.get("fulfillmentOrderReleaseHold") or {}
        return self._success(
            Capability.SHOPIFY_RELEASE_FULFILLMENT_ORDER_HOLD,
            data={
                "fulfillment_order": self._normalise_fulfillment_order(
                    payload.get("fulfillmentOrder") or {},
                ),
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_hold_input(self, params: dict[str, Any]) -> dict[str, Any]:
        reason = params.get("reason")
        if not isinstance(reason, str) or reason.upper() not in _VALID_REASONS:
            raise AdapterValidationError(
                self.name,
                f"'reason' is required and must be one of: "
                f"{sorted(_VALID_REASONS)}",
            )

        out: dict[str, Any] = {"reason": reason.upper()}

        reason_notes = params.get("reason_notes") or params.get("reasonNotes")
        if reason_notes is not None:
            if not isinstance(reason_notes, str):
                raise AdapterValidationError(
                    self.name, "'reason_notes' must be a string",
                )
            out["reasonNotes"] = reason_notes

        notify_merchant = params.get("notify_merchant")
        if notify_merchant is None:
            notify_merchant = params.get("notifyMerchant")
        if notify_merchant is not None:
            out["notifyMerchant"] = bool(notify_merchant)

        external_id = params.get("external_id") or params.get("externalId")
        if external_id is not None:
            if not isinstance(external_id, str):
                raise AdapterValidationError(
                    self.name, "'external_id' must be a string",
                )
            out["externalId"] = external_id.strip()

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_fulfillment_order(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        holds_raw = node.get("fulfillmentHolds") or []
        holds = []
        for h in holds_raw:
            if not isinstance(h, dict):
                continue
            held_by = h.get("heldByApp") or {}
            holds.append({
                "id": h.get("id", "") or "",
                "reason": h.get("reason", "") or "",
                "reason_notes": h.get("reasonNotes", "") or "",
                "held_by_app_id": (
                    held_by.get("id", "")
                    if isinstance(held_by, dict) else ""
                ) or "",
            })
        return {
            "id": node.get("id", "") or "",
            "status": node.get("status", "") or "",
            "request_status": node.get("requestStatus", "") or "",
            "holds": holds,
            "is_held": bool(holds),
        }
