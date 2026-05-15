"""ShopifyOrderTransactionsAdapter — payment transaction details.

Order transactions are the per-payment ledger entries for an order:
the original AUTHORIZATION, the CAPTURE that drew funds, any
REFUND, the gateway-specific transaction ID, and the receipt blob
the payment processor returned.

ShopAI's analytics + risk engines read transactions to:

  * Reconcile gross-to-net revenue (subtract refunds and dispute
    losses by gateway).
  * Detect fraud patterns ("this gateway has 30% chargeback rate
    on this customer segment").
  * Verify payment processor for routing decisions ("Stripe
    customer → use Stripe Connect for subscription billing").
  * Forensics on disputed orders — the receipt blob carries the
    raw network response from the issuing bank.

Capabilities (read-only — creating transactions on existing orders
needs orderTransactionCreate which is a high-stakes mutation that
should stay manual / merchant-driven):

  * ``SHOPIFY_LIST_ORDER_TRANSACTIONS`` — list per-order transactions.
  * ``SHOPIFY_GET_TRANSACTION``         — single transaction with
    full gateway receipt.

Pattern A: transactions are reached through the order node
(``order(id:).transactions``) — there's no top-level
``Query.transactions`` connection. Same pattern as
customer.paymentMethods.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_TRANSACTION_FIELDS = """
id
kind
status
gateway
test
authorizationCode
processedAt
errorCode
formattedGateway
manuallyCapturable
parentTransaction {
  id
}
amountSet {
  shopMoney { amount currencyCode }
}
totalUnsettledSet {
  shopMoney { amount currencyCode }
}
fees {
  amount {
    amount
    currencyCode
  }
  flatFee {
    amount
    currencyCode
  }
  flatFeeName
  rate
  rateName
  type
}
""".strip()


_LIST_TRANSACTIONS_QUERY = f"""
query orderTransactions($id: ID!, $first: Int, $capturable: Boolean) {{
  order(id: $id) {{
    id
    name
    transactions(first: $first, capturable: $capturable) {{
      {_TRANSACTION_FIELDS}
    }}
  }}
}}
""".strip()


_GET_TRANSACTION_QUERY = f"""
query orderTransaction($id: ID!) {{
  node(id: $id) {{
    ... on OrderTransaction {{
      {_TRANSACTION_FIELDS}
      receiptJson
    }}
  }}
}}
""".strip()


_DEFAULT_LIMIT = 50
_MAX_LIMIT = 250


class ShopifyOrderTransactionsAdapter(ShopifyBaseAdapter):
    name = "shopify_order_transactions"
    capabilities = {
        Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS,
        Capability.SHOPIFY_GET_TRANSACTION,
    }
    required_scopes = frozenset({"read_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_TRANSACTION:
            return self._get(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        order_id = params.get("order_id") or params.get("orderId")
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'order_id' (Shopify GID) is required — Shopify "
                "doesn't expose a top-level transactions connection",
            )

        limit = params.get("limit", _DEFAULT_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        variables: dict[str, Any] = {
            "id": order_id.strip(),
            "first": limit,
        }

        capturable = params.get("capturable")
        if capturable is not None:
            variables["capturable"] = bool(capturable)

        data = self._gql(_LIST_TRANSACTIONS_QUERY, variables)
        order = data.get("order") or {}
        # Pattern: order.transactions returns a flat list, not an
        # edges/node connection. Same shape as Order.taxLines.
        transactions_raw = order.get("transactions") or []
        transactions = [
            self._normalise_transaction(t)
            for t in transactions_raw if isinstance(t, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_ORDER_TRANSACTIONS,
            data={
                "order_id": order.get("id", "") or "",
                "order_name": order.get("name", "") or "",
                "transactions": transactions,
                "count": len(transactions),
                "order_found": bool(order),
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        transaction_id = params.get("id") or params.get("transaction_id")
        if not isinstance(transaction_id, str) or not transaction_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the order transaction) is required",
            )
        data = self._gql(_GET_TRANSACTION_QUERY, {
            "id": transaction_id.strip(),
        })
        node = data.get("node") or {}
        normalised = self._normalise_transaction(node, with_receipt=True)
        return self._success(
            Capability.SHOPIFY_GET_TRANSACTION,
            data={
                "transaction": normalised,
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
    def _normalise_transaction(
        cls, node: dict[str, Any], with_receipt: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        amount, currency = cls._money(node.get("amountSet"))
        unsettled, _ = cls._money(node.get("totalUnsettledSet"))
        parent = node.get("parentTransaction") or {}
        fees_raw = node.get("fees") or []
        fees = [
            cls._normalise_fee(f) for f in fees_raw
            if isinstance(f, dict)
        ]
        out = {
            "id": node.get("id", "") or "",
            "kind": node.get("kind", "") or "",
            "status": node.get("status", "") or "",
            "gateway": node.get("gateway", "") or "",
            "formatted_gateway": node.get("formattedGateway", "") or "",
            "test": bool(node.get("test", False)),
            "authorization_code": node.get("authorizationCode", "") or "",
            "error_code": node.get("errorCode", "") or "",
            "manually_capturable": bool(
                node.get("manuallyCapturable", False),
            ),
            "processed_at": node.get("processedAt", "") or "",
            "amount": amount,
            "currency_code": currency,
            "total_unsettled": unsettled,
            "parent_transaction_id": (
                parent.get("id", "")
                if isinstance(parent, dict) else ""
            ) or "",
            "fees": fees,
        }
        if with_receipt:
            # receiptJson is a JSON-string the gateway returned.
            # We pass it through verbatim — analytics consumers can
            # parse it themselves rather than the adapter making a
            # call about the schema.
            out["receipt_json"] = node.get("receiptJson", "") or ""
        return out

    @classmethod
    def _normalise_fee(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        amount = node.get("amount") or {}
        flat = node.get("flatFee") or {}
        return {
            "type": node.get("type", "") or "",
            "amount": (
                amount.get("amount", "")
                if isinstance(amount, dict) else ""
            ) or "",
            "currency_code": (
                amount.get("currencyCode", "")
                if isinstance(amount, dict) else ""
            ) or "",
            "flat_fee_amount": (
                flat.get("amount", "") if isinstance(flat, dict) else ""
            ) or "",
            "flat_fee_currency": (
                flat.get("currencyCode", "")
                if isinstance(flat, dict) else ""
            ) or "",
            "flat_fee_name": node.get("flatFeeName", "") or "",
            "rate": float(node.get("rate") or 0),
            "rate_name": node.get("rateName", "") or "",
        }
