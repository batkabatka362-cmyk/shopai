"""ShopifyRefundAdapter — create refunds on existing orders.

Fills the ``SHOPIFY_CREATE_REFUND`` gap. Needed by:

  * The CS agent when a dispute is resolved in the customer's
    favour — refund a percentage of the order without touching
    fulfillment.
  * The chargeback-prevention flow when Shopify's risk adapter
    flags a HIGH-risk order post-capture.
  * The loyalty make-good workflow when a product review
    indicates a defective unit.

WRITE-ONLY. Reading an existing order's refund history belongs
to ``ShopifyOrdersAdapter`` (already fetches refunds inline).

Two refund flows are supported in a single entrypoint:

  * **Full refund** — refund the entire remaining balance plus
    shipping. Trigger by omitting ``refund_line_items`` AND
    passing ``refund_full: true`` or ``amount`` matching the
    order total.

  * **Partial refund** — refund specific line-item quantities
    (``refund_line_items``), a specific ``amount`` on the
    default gateway transaction, or both.

Params shape::

    {
        "order_id":        "123" | "gid://shopify/Order/123",   # required
        "reason":          "customer",                # free-form note
        "notify":          True,                      # send refund email
        "refund_full":     False,                     # refund everything remaining
        "amount":          12.50,                     # override amount to refund (default gateway)
        "currency":        "USD",                     # required if amount given
        "refund_line_items": [                        # optional
            {
                "line_item_id":  "gid://shopify/LineItem/999",
                "quantity":       2,
                "restock_type":  "return"|"cancel"|"no_restock",
                "location_id":   "gid://shopify/Location/1",    # for restock=return
            },
            ...
        ],
        "refund_shipping": {                          # optional
            "full_refund": True,
            "amount":      5.00,
        },
    }

At least ONE of ``amount``, ``refund_line_items``, or
``refund_shipping`` must be present (OR ``refund_full=True``);
otherwise the adapter raises ``AdapterValidationError`` rather
than fire a zero-value refund.

Returns::

    {
        "order_id":     "gid://shopify/Order/123",
        "refund_id":    "gid://shopify/Refund/555",
        "note":         "...",
        "total_refunded": "12.50",
        "currency":     "USD",
        "restocked":    True,
        "created_at":   "2026-04-14T12:00:00Z",
    }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_REFUND_CREATE_MUTATION = """
mutation RefundCreate($input: RefundInput!) {
  refundCreate(input: $input) {
    refund {
      id
      note
      createdAt
      totalRefundedSet {
        presentmentMoney { amount currencyCode }
        shopMoney { amount currencyCode }
      }
      refundLineItems(first: 50) {
        edges {
          node {
            quantity
            restockType
            lineItem { id }
          }
        }
      }
    }
    order {
      id
      name
      totalRefundedSet {
        presentmentMoney { amount currencyCode }
      }
    }
    userErrors { field message code }
  }
}
""".strip()


_ORDER_TRANSACTIONS_QUERY = """
query OrderForRefund($id: ID!) {
  order(id: $id) {
    id
    name
    currencyCode
    totalOutstandingSet {
      shopMoney { amount currencyCode }
    }
    transactions(first: 20) {
      id
      kind
      status
      gateway
      parentTransaction { id }
      amountSet { shopMoney { amount currencyCode } }
    }
  }
}
""".strip()


_RESTOCK_TYPES = {"return", "cancel", "no_restock", "legacy_restock"}


class ShopifyRefundAdapter(ShopifyBaseAdapter):
    """Create a refund on an existing Shopify order."""

    name = "shopify_refund"
    capabilities = {Capability.SHOPIFY_CREATE_REFUND}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_CREATE_REFUND:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        order_id = params.get("order_id")
        if not order_id:
            raise AdapterValidationError(
                self.name, "'order_id' is required",
            )
        order_gid = self._to_gid(order_id, "Order")

        refund_line_items = params.get("refund_line_items") or []
        refund_shipping = params.get("refund_shipping")
        amount = params.get("amount")
        refund_full = bool(params.get("refund_full", False))

        if (
            not refund_line_items
            and not refund_shipping
            and amount is None
            and not refund_full
        ):
            raise AdapterValidationError(
                self.name,
                "at least one of 'refund_line_items', 'refund_shipping', "
                "'amount', or 'refund_full=True' is required",
            )

        # ── Build RefundLineItemInput[] ───────────────────────
        line_items_input: list[dict[str, Any]] = []
        if refund_line_items:
            if not isinstance(refund_line_items, list):
                raise AdapterValidationError(
                    self.name, "'refund_line_items' must be a list",
                )
            for i, item in enumerate(refund_line_items):
                if not isinstance(item, dict):
                    raise AdapterValidationError(
                        self.name,
                        f"refund_line_items[{i}] must be a dict",
                    )
                li_id = item.get("line_item_id")
                if not li_id:
                    raise AdapterValidationError(
                        self.name,
                        f"refund_line_items[{i}].line_item_id is required",
                    )
                try:
                    qty = int(item.get("quantity", 1))
                except (TypeError, ValueError):
                    raise AdapterValidationError(
                        self.name,
                        f"refund_line_items[{i}].quantity must be an integer",
                    )
                if qty <= 0:
                    raise AdapterValidationError(
                        self.name,
                        f"refund_line_items[{i}].quantity must be > 0",
                    )

                restock = str(item.get("restock_type") or "no_restock").lower()
                if restock not in _RESTOCK_TYPES:
                    raise AdapterValidationError(
                        self.name,
                        f"refund_line_items[{i}].restock_type must be "
                        f"one of {sorted(_RESTOCK_TYPES)}",
                    )

                entry: dict[str, Any] = {
                    "lineItemId": self._to_gid(li_id, "LineItem"),
                    "quantity": qty,
                    "restockType": restock.upper(),
                }
                # Restock-to-location only makes sense when the
                # restock type is RETURN — Shopify rejects it
                # otherwise.
                if restock == "return" and item.get("location_id"):
                    entry["locationId"] = self._to_gid(
                        item["location_id"], "Location",
                    )
                line_items_input.append(entry)

        # ── Build transactions[] ─────────────────────────────
        # If the caller passes `amount`, we refund that against
        # the default capture transaction. Shopify demands a
        # parentId for every refund transaction, so we fetch the
        # order's transactions and pick the most recent CAPTURE
        # / SALE.
        transactions_input: list[dict[str, Any]] = []
        resolved_currency = ""
        if amount is not None or refund_full:
            parent_id, parent_currency, outstanding = \
                self._resolve_parent_transaction(order_gid)
            if amount is None and refund_full:
                if not outstanding:
                    raise AdapterValidationError(
                        self.name,
                        "cannot infer refund amount — order has no "
                        "outstanding balance",
                    )
                amount_val = float(outstanding)
            else:
                try:
                    amount_val = float(amount)
                except (TypeError, ValueError):
                    raise AdapterValidationError(
                        self.name, "'amount' must be a number",
                    )
                if amount_val <= 0:
                    raise AdapterValidationError(
                        self.name, "'amount' must be > 0",
                    )

            currency = str(
                params.get("currency") or parent_currency or "",
            ).strip().upper()
            if not currency:
                raise AdapterValidationError(
                    self.name,
                    "'currency' is required when refunding an amount",
                )
            resolved_currency = currency

            transactions_input.append({
                "orderId": order_gid,
                "parentId": parent_id,
                "amount": f"{amount_val:.2f}",
                "gateway": "manual",
                "kind": "REFUND",
            })

        # ── Build shipping input ─────────────────────────────
        shipping_input: dict[str, Any] | None = None
        if refund_shipping:
            if not isinstance(refund_shipping, dict):
                raise AdapterValidationError(
                    self.name, "'refund_shipping' must be a dict",
                )
            shipping_input = {}
            if refund_shipping.get("full_refund"):
                shipping_input["fullRefund"] = True
            ship_amount = refund_shipping.get("amount")
            if ship_amount is not None:
                try:
                    ship_val = float(ship_amount)
                except (TypeError, ValueError):
                    raise AdapterValidationError(
                        self.name,
                        "'refund_shipping.amount' must be a number",
                    )
                if ship_val < 0:
                    raise AdapterValidationError(
                        self.name,
                        "'refund_shipping.amount' must be >= 0",
                    )
                shipping_input["amount"] = f"{ship_val:.2f}"
            if not shipping_input:
                shipping_input = None

        # ── Compose RefundInput ──────────────────────────────
        refund_input: dict[str, Any] = {
            "orderId": order_gid,
            "notify": bool(params.get("notify", False)),
        }
        reason = params.get("reason")
        if reason:
            refund_input["note"] = str(reason)
        if line_items_input:
            refund_input["refundLineItems"] = line_items_input
        if transactions_input:
            refund_input["transactions"] = transactions_input
        if shipping_input:
            refund_input["shipping"] = shipping_input

        data = self._gql(
            _REFUND_CREATE_MUTATION, {"input": refund_input},
        )
        self._check_user_errors(data, "refundCreate")

        payload = data.get("refundCreate") or {}
        refund = payload.get("refund") or {}
        total_set = (refund.get("totalRefundedSet") or {})
        shop_money = total_set.get("shopMoney") or {}

        # Determine whether anything was restocked so callers can
        # reflect that in the UI without re-parsing refund line items.
        restocked = False
        for edge in (refund.get("refundLineItems") or {}).get("edges", []) or []:
            rtype = ((edge.get("node") or {}).get("restockType") or "").upper()
            if rtype in ("RETURN", "LEGACY_RESTOCK"):
                restocked = True
                break

        return self._success(
            Capability.SHOPIFY_CREATE_REFUND,
            data={
                "order_id": order_gid,
                "refund_id": refund.get("id", "") or "",
                "note": refund.get("note", "") or "",
                "total_refunded": shop_money.get("amount", "0") or "0",
                "currency": (
                    shop_money.get("currencyCode", "")
                    or resolved_currency
                    or ""
                ),
                "restocked": restocked,
                "created_at": refund.get("createdAt", "") or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────

    def _resolve_parent_transaction(
        self, order_gid: str,
    ) -> tuple[str, str, str]:
        """Pick the transaction on ``order_gid`` that a refund
        should be applied against.

        Returns ``(parent_id, currency, outstanding_amount)``.
        """
        data = self._gql(_ORDER_TRANSACTIONS_QUERY, {"id": order_gid})
        order = data.get("order")
        if not order:
            raise AdapterValidationError(
                self.name, f"order not found: {order_gid}",
            )
        txns = order.get("transactions") or []
        # Prefer the most recent SUCCESS CAPTURE, then SUCCESS
        # SALE, as the refund parent. Authorizations without
        # capture cannot be refunded — they must be voided
        # instead.
        priority = {"CAPTURE": 0, "SALE": 1}
        best: tuple[int, str, str] | None = None
        for t in txns:
            kind = (t.get("kind") or "").upper()
            status = (t.get("status") or "").upper()
            if status != "SUCCESS" or kind not in priority:
                continue
            amount_set = (t.get("amountSet") or {}).get("shopMoney") or {}
            currency = amount_set.get("currencyCode", "")
            tid = t.get("id", "")
            if not tid:
                continue
            score = priority[kind]
            if best is None or score < best[0]:
                best = (score, tid, currency)
        if best is None:
            raise AdapterValidationError(
                self.name,
                f"no successful capture/sale transaction on {order_gid} "
                "— refund not possible",
            )
        _, parent_id, currency = best

        # Outstanding amount = what's still refundable. Used by
        # refund_full=True to compute the amount without
        # requiring the caller to pass one.
        outstanding_money = (
            (order.get("totalOutstandingSet") or {}).get("shopMoney") or {}
        )
        outstanding = str(outstanding_money.get("amount", "0") or "0")
        currency = currency or order.get("currencyCode", "") or ""
        return parent_id, currency, outstanding

    @staticmethod
    def _to_gid(value: Any, resource: str) -> str:
        """Accept numeric id, string id, or full GID and return
        canonical ``gid://shopify/{resource}/{id}``."""
        s = str(value)
        if s.startswith("gid://"):
            return s
        return f"gid://shopify/{resource}/{s}"
