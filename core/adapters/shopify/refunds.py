"""ShopifyRefundsAdapter — issue refunds and read refund history.

Refunds are the financial twin of returns: ``ShopifyReturnsAdapter``
manages the *physical* return record (RMA, line-item restock,
approval state) while this adapter manages the *money movement*
(charge reversal, partial vs full, shipping refund).

The two were deliberately split (see ShopifyReturnsAdapter docstring)
because conflating them muddies the audit trail — a return can exist
without a refund (replacement-shipped instead of refund) and a refund
can exist without a return (post-purchase discount applied as
goodwill). Engines call whichever they actually need.

ShopAI use cases:

  * **Auto-refund on cancel.** When the ROAS guardrail kills a
    pending order before it ships, the engine refunds the customer
    rather than letting the charge sit.
  * **Make-good refund.** Customer-service automation issues a
    partial refund (e.g. shipping-only) for damaged-in-transit
    complaints without forcing a full RMA dance.
  * **Refund analytics.** The refund-rate dashboard reads the per-
    order refund history to spot outliers ("this product has 30%
    refund rate — pull from secondary channels").

Capabilities:

  * ``SHOPIFY_CREATE_REFUND``       — issue a refund via
    ``refundCreate``. Requires the order id and the transaction(s)
    to refund against; the engine picks the parent transaction
    from the order's existing transactions list.
  * ``SHOPIFY_LIST_ORDER_REFUNDS``  — page through refunds on a
    specific order (refunds don't have a top-level connection,
    same pattern as returns: traverse via the order).
  * ``SHOPIFY_GET_REFUND``          — fetch one refund with its
    line items and transactions.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


# Common selection set for refund nodes — used by list and get so
# the normaliser only knows one shape.
_REFUND_NODE_FIELDS = """
id
note
createdAt
updatedAt
totalRefundedSet {
  presentmentMoney { amount currencyCode }
}
order {
  id
  name
}
refundLineItems(first: 50) {
  edges {
    node {
      id
      quantity
      restockType
      lineItem {
        id
        title
        sku
      }
      subtotalSet {
        presentmentMoney { amount currencyCode }
      }
    }
  }
}
transactions(first: 20) {
  edges {
    node {
      id
      kind
      status
      gateway
      amountSet {
        presentmentMoney { amount currencyCode }
      }
    }
  }
}
""".strip()


_CREATE_REFUND_MUTATION = f"""
mutation refundCreate($input: RefundInput!) {{
  refundCreate(input: $input) {{
    refund {{
      {_REFUND_NODE_FIELDS}
    }}
    order {{
      id
      name
      displayFinancialStatus
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_GET_REFUND_QUERY = f"""
query getRefund($id: ID!) {{
  refund(id: $id) {{
    {_REFUND_NODE_FIELDS}
  }}
}}
""".strip()


_LIST_ORDER_REFUNDS_QUERY = f"""
query orderRefunds($orderId: ID!, $first: Int!) {{
  order(id: $orderId) {{
    id
    name
    refunds(first: $first) {{
      {_REFUND_NODE_FIELDS}
    }}
  }}
}}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


# RefundLineItemRestockType enum aliases. Engines often pass natural
# words; map to canonical UPPER_SNAKE values.
_RESTOCK_TYPES = {
    "no_restock": "NO_RESTOCK",
    "none": "NO_RESTOCK",
    "cancel": "CANCEL",
    "return": "RETURN",
    "legacy_restock": "LEGACY_RESTOCK",
}


class ShopifyRefundsAdapter(ShopifyBaseAdapter):
    name = "shopify_refunds"
    capabilities = {
        Capability.SHOPIFY_CREATE_REFUND,
        Capability.SHOPIFY_LIST_ORDER_REFUNDS,
        Capability.SHOPIFY_GET_REFUND,
    }
    # Refunds ride on the orders scope.
    required_scopes = frozenset({"read_orders", "write_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_REFUND:
            return self._create_refund(params)
        if capability == Capability.SHOPIFY_LIST_ORDER_REFUNDS:
            return self._list_order_refunds(params)
        if capability == Capability.SHOPIFY_GET_REFUND:
            return self._get_refund(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create refund ──────────────────────────────────────────────

    def _create_refund(self, params: dict[str, Any]) -> Any:
        refund_input = self._build_refund_input(params)
        data = self._gql(_CREATE_REFUND_MUTATION, {"input": refund_input})
        self._check_user_errors(data, "refundCreate")
        payload = data.get("refundCreate") or {}
        refund = payload.get("refund") or {}
        order = payload.get("order") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_REFUND,
            data={
                "refund": self._normalise_refund(refund),
                "order_id": order.get("id", "") or "",
                "order_name": order.get("name", "") or "",
                "order_financial_status": order.get(
                    "displayFinancialStatus", "",
                ) or "",
            },
        )

    @staticmethod
    def _build_refund_input(params: dict[str, Any]) -> dict[str, Any]:
        """Convert ShopAI's friendly call shape into ``RefundInput``.

        Friendly form::

            {
              "order_id": "gid://shopify/Order/X",
              "note":     "Damaged in transit, refunded shipping",
              "notify":   True,
              "currency": "USD",
              "shipping": {"full_refund": True}      # OR
                          {"amount": "10.00"},
              "transactions": [
                  {"parent_id": "gid://shopify/OrderTransaction/Y",
                   "amount":    "25.50",
                   "gateway":   "manual",
                   "kind":      "REFUND"},  # default REFUND
              ],
              "refund_line_items": [
                  {"line_item_id": "gid://shopify/LineItem/L",
                   "quantity": 1,
                   "restock_type": "no_restock"},
              ],
            }

        Validation up-front: order_id required, at least one of
        ``transactions`` / ``refund_line_items`` / ``shipping`` must
        be provided (a refund with none is a no-op and Shopify
        rejects it). Money values are coerced to 2-decimal strings.
        """
        order_id = params.get("order_id") or params.get("orderId")
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                "shopify_refunds",
                "'order_id' (Shopify GID for the order) is required",
            )

        transactions_raw = params.get("transactions")
        refund_line_items_raw = (
            params.get("refund_line_items") or params.get("refundLineItems")
        )
        shipping_raw = params.get("shipping")

        if not (transactions_raw or refund_line_items_raw or shipping_raw):
            raise AdapterValidationError(
                "shopify_refunds",
                "refund needs at least one of 'transactions', "
                "'refund_line_items', or 'shipping' — a refund with "
                "no money movement is a no-op and Shopify rejects it",
            )

        out: dict[str, Any] = {"orderId": order_id.strip()}

        note = params.get("note")
        if note:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    "shopify_refunds", "'note' must be a string",
                )
            out["note"] = note

        notify = params.get("notify")
        if notify is not None:
            out["notify"] = bool(notify)

        currency = params.get("currency") or params.get("currencyCode")
        if currency:
            if not isinstance(currency, str):
                raise AdapterValidationError(
                    "shopify_refunds", "'currency' must be a string",
                )
            out["currency"] = currency.upper()

        if transactions_raw is not None:
            if not isinstance(transactions_raw, list) or not transactions_raw:
                raise AdapterValidationError(
                    "shopify_refunds",
                    "'transactions' must be a non-empty list",
                )
            tx_out: list[dict[str, Any]] = []
            for i, tx in enumerate(transactions_raw):
                # ``OrderTransactionInput.orderId`` is required by
                # Shopify (caught live as 'Expected value to not be
                # null'). The caller already provides the parent
                # order at the top level — propagate it down so
                # engines don't have to repeat it per-transaction.
                if isinstance(tx, dict) and not (
                    tx.get("order_id") or tx.get("orderId")
                ):
                    tx = {**tx, "order_id": order_id.strip()}
                tx_out.append(_build_tx_input(tx, i))
            out["transactions"] = tx_out

        if refund_line_items_raw is not None:
            if not isinstance(refund_line_items_raw, list) or not refund_line_items_raw:
                raise AdapterValidationError(
                    "shopify_refunds",
                    "'refund_line_items' must be a non-empty list",
                )
            li_out: list[dict[str, Any]] = []
            for i, li in enumerate(refund_line_items_raw):
                li_out.append(_build_refund_line_item(li, i))
            out["refundLineItems"] = li_out

        if shipping_raw is not None:
            if not isinstance(shipping_raw, dict):
                raise AdapterValidationError(
                    "shopify_refunds",
                    "'shipping' must be a dict {full_refund} or {amount}",
                )
            full_refund = shipping_raw.get("full_refund") or shipping_raw.get("fullRefund")
            amount = shipping_raw.get("amount")
            if full_refund is None and amount is None:
                raise AdapterValidationError(
                    "shopify_refunds",
                    "'shipping' needs either 'full_refund' (bool) or "
                    "'amount' (decimal string)",
                )
            shipping_out: dict[str, Any] = {}
            if full_refund is not None:
                shipping_out["fullRefund"] = bool(full_refund)
            if amount is not None:
                try:
                    shipping_out["amount"] = f"{float(amount):.2f}"
                except (TypeError, ValueError) as exc:
                    raise AdapterValidationError(
                        "shopify_refunds",
                        "'shipping.amount' must be numeric",
                    ) from exc
            out["shipping"] = shipping_out

        return out

    # ── List refunds for an order ─────────────────────────────────

    def _list_order_refunds(self, params: dict[str, Any]) -> Any:
        order_id = params.get("order_id") or params.get("orderId")
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                "shopify_refunds",
                "'order_id' (Shopify GID for the order) is required",
            )
        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        data = self._gql(_LIST_ORDER_REFUNDS_QUERY, {
            "orderId": order_id.strip(),
            "first": limit,
        })
        order = data.get("order")
        if not isinstance(order, dict):
            return self._success(
                Capability.SHOPIFY_LIST_ORDER_REFUNDS,
                data={
                    "order_id": order_id.strip(),
                    "found": False,
                    "refunds": [],
                    "count": 0,
                },
            )
        refunds_raw = order.get("refunds") or []
        # Note: Order.refunds is a list (not a connection), so no
        # pagination cursor — the caller's `limit` caps it.
        if not isinstance(refunds_raw, list):
            refunds_raw = []
        refunds = [
            self._normalise_refund(r) for r in refunds_raw
            if isinstance(r, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_ORDER_REFUNDS,
            data={
                "order_id": order.get("id", "") or order_id.strip(),
                "order_name": order.get("name", "") or "",
                "found": True,
                "refunds": refunds,
                "count": len(refunds),
            },
        )

    # ── Get one refund ─────────────────────────────────────────────

    def _get_refund(self, params: dict[str, Any]) -> Any:
        refund_id = params.get("id") or params.get("refund_id")
        if not isinstance(refund_id, str) or not refund_id.strip():
            raise AdapterValidationError(
                "shopify_refunds",
                "'id' (Shopify GID for the refund) is required",
            )
        data = self._gql(_GET_REFUND_QUERY, {"id": refund_id.strip()})
        node = data.get("refund")
        if not isinstance(node, dict):
            return self._success(
                Capability.SHOPIFY_GET_REFUND,
                data={"found": False, "refund": None},
            )
        return self._success(
            Capability.SHOPIFY_GET_REFUND,
            data={"found": True, "refund": self._normalise_refund(node)},
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_refund(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        order = node.get("order") or {}

        def _money(field_name: str) -> tuple[float, str]:
            field = node.get(field_name) or {}
            money = (
                field.get("presentmentMoney")
                if isinstance(field, dict) else None
            ) or {}
            try:
                amount = float(money.get("amount", 0) or 0)
            except (TypeError, ValueError):
                amount = 0.0
            return amount, money.get("currencyCode", "") or ""

        total, currency = _money("totalRefundedSet")

        line_items: list[dict[str, Any]] = []
        li_envelope = node.get("refundLineItems") or {}
        if isinstance(li_envelope, dict):
            for edge in li_envelope.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                li_node = edge.get("node") or {}
                line = li_node.get("lineItem") or {}
                subtotal_field = li_node.get("subtotalSet") or {}
                subtotal_money = (
                    subtotal_field.get("presentmentMoney")
                    if isinstance(subtotal_field, dict) else None
                ) or {}
                try:
                    subtotal = float(subtotal_money.get("amount", 0) or 0)
                except (TypeError, ValueError):
                    subtotal = 0.0
                line_items.append({
                    "id": li_node.get("id", "") or "",
                    "quantity": int(li_node.get("quantity", 0) or 0),
                    "restock_type": li_node.get("restockType", "") or "",
                    "product_title": (
                        line.get("title", "") if isinstance(line, dict) else ""
                    ) or "",
                    "sku": (
                        line.get("sku", "") if isinstance(line, dict) else ""
                    ) or "",
                    "subtotal": subtotal,
                })

        transactions: list[dict[str, Any]] = []
        tx_envelope = node.get("transactions") or {}
        if isinstance(tx_envelope, dict):
            for edge in tx_envelope.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                tx_node = edge.get("node") or {}
                amount_field = tx_node.get("amountSet") or {}
                amount_money = (
                    amount_field.get("presentmentMoney")
                    if isinstance(amount_field, dict) else None
                ) or {}
                try:
                    tx_amount = float(amount_money.get("amount", 0) or 0)
                except (TypeError, ValueError):
                    tx_amount = 0.0
                transactions.append({
                    "id": tx_node.get("id", "") or "",
                    "kind": tx_node.get("kind", "") or "",
                    "status": tx_node.get("status", "") or "",
                    "gateway": tx_node.get("gateway", "") or "",
                    "amount": tx_amount,
                })

        return {
            "id": node.get("id", "") or "",
            "note": node.get("note", "") or "",
            "total": total,
            "currency": currency,
            "order_id": order.get("id", "") or "",
            "order_name": order.get("name", "") or "",
            "line_items": line_items,
            "transactions": transactions,
            "created_at": node.get("createdAt", "") or "",
            "updated_at": node.get("updatedAt", "") or "",
        }


def _build_tx_input(tx: Any, idx: int) -> dict[str, Any]:
    """Validate and normalise one transaction entry."""
    if not isinstance(tx, dict):
        raise AdapterValidationError(
            "shopify_refunds",
            f"transactions[{idx}] must be a dict",
        )
    parent_id = tx.get("parent_id") or tx.get("parentId")
    if not isinstance(parent_id, str) or not parent_id.strip():
        raise AdapterValidationError(
            "shopify_refunds",
            f"transactions[{idx}] needs 'parent_id' (the original "
            f"OrderTransaction GID being refunded against)",
        )
    amount = tx.get("amount")
    if amount is None:
        raise AdapterValidationError(
            "shopify_refunds",
            f"transactions[{idx}] needs 'amount'",
        )
    try:
        amount_str = f"{float(amount):.2f}"
    except (TypeError, ValueError) as exc:
        raise AdapterValidationError(
            "shopify_refunds",
            f"transactions[{idx}] 'amount' must be numeric",
        ) from exc
    if float(amount_str) <= 0:
        raise AdapterValidationError(
            "shopify_refunds",
            f"transactions[{idx}] 'amount' must be > 0",
        )
    gateway = tx.get("gateway", "manual")
    if not isinstance(gateway, str) or not gateway.strip():
        raise AdapterValidationError(
            "shopify_refunds",
            f"transactions[{idx}] 'gateway' must be a non-empty string",
        )
    kind = (tx.get("kind") or "REFUND").upper()
    if kind not in {"REFUND", "VOID"}:
        raise AdapterValidationError(
            "shopify_refunds",
            f"transactions[{idx}] 'kind' must be REFUND or VOID, "
            f"got {kind!r}",
        )
    out: dict[str, Any] = {
        "parentId": parent_id.strip(),
        "amount": amount_str,
        "gateway": gateway.strip(),
        "kind": kind,
    }
    order_id = tx.get("order_id") or tx.get("orderId")
    if order_id:
        if not isinstance(order_id, str):
            raise AdapterValidationError(
                "shopify_refunds",
                f"transactions[{idx}] 'order_id' must be a string",
            )
        out["orderId"] = order_id.strip()
    return out


def _build_refund_line_item(li: Any, idx: int) -> dict[str, Any]:
    """Validate and normalise one refund line item entry."""
    if not isinstance(li, dict):
        raise AdapterValidationError(
            "shopify_refunds",
            f"refund_line_items[{idx}] must be a dict",
        )
    line_id = li.get("line_item_id") or li.get("lineItemId")
    if not isinstance(line_id, str) or not line_id.strip():
        raise AdapterValidationError(
            "shopify_refunds",
            f"refund_line_items[{idx}] needs 'line_item_id'",
        )
    quantity = li.get("quantity")
    try:
        qty = int(quantity)
    except (TypeError, ValueError) as exc:
        raise AdapterValidationError(
            "shopify_refunds",
            f"refund_line_items[{idx}] 'quantity' must be int",
        ) from exc
    if qty < 1:
        raise AdapterValidationError(
            "shopify_refunds",
            f"refund_line_items[{idx}] 'quantity' must be >= 1",
        )
    restock_type_raw = (
        li.get("restock_type") or li.get("restockType") or "NO_RESTOCK"
    )
    if not isinstance(restock_type_raw, str):
        raise AdapterValidationError(
            "shopify_refunds",
            f"refund_line_items[{idx}] 'restock_type' must be a string",
        )
    restock_type = _RESTOCK_TYPES.get(
        restock_type_raw.lower(), restock_type_raw.upper(),
    )
    if restock_type not in {"NO_RESTOCK", "CANCEL", "RETURN", "LEGACY_RESTOCK"}:
        raise AdapterValidationError(
            "shopify_refunds",
            f"refund_line_items[{idx}] 'restock_type' must be one of "
            f"NO_RESTOCK / CANCEL / RETURN / LEGACY_RESTOCK, "
            f"got {restock_type_raw!r}",
        )
    out: dict[str, Any] = {
        "lineItemId": line_id.strip(),
        "quantity": qty,
        "restockType": restock_type,
    }
    location_id = li.get("location_id") or li.get("locationId")
    if location_id:
        if not isinstance(location_id, str):
            raise AdapterValidationError(
                "shopify_refunds",
                f"refund_line_items[{idx}] 'location_id' must be a string",
            )
        out["locationId"] = location_id.strip()
    return out
