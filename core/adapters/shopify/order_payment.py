"""ShopifyOrderPaymentAdapter — capture authorisations + void transactions.

Companions:
  * ``order_transactions.py`` reads the existing transaction
    history (authorisations, captures, refunds, voids).
  * ``orders.py`` + ``order_lifecycle.py`` cover order-level
    state changes (cancel/close/reopen/markAsPaid).

This adapter ships the two transaction-level write primitives
that are missing — finalising an authorisation into a charge,
and voiding an unfunded transaction:

  * **Manual capture flow.** Operator (or fraud engine) reviews
    an authorisation, decides the order is clean, captures the
    charge. Useful when the storefront is configured for
    manual-capture authorisation rather than auto-capture.
  * **Pre-cancel void.** When an order is being cancelled
    BEFORE capture (still authorisation-only), voiding the auth
    releases the hold on the buyer's card faster than waiting
    for the auth to expire.

Capabilities:

  * ``SHOPIFY_CAPTURE_ORDER_PAYMENT`` — orderCapture. Single
    input dict (Pattern A inside the input): ``id`` (order
    GID), ``parentTransactionId`` (the auth to capture against),
    ``amount`` + optional ``currency``, optional ``finalCapture``.
  * ``SHOPIFY_VOID_TRANSACTION``     — transactionVoid. Pattern
    A: ``parentTransactionId`` at the GraphQL field level.

Pattern F: ``orderCapture``'s userErrors are typed ``UserError``
(no ``code``). ``transactionVoid``'s userErrors are typed
``TransactionVoidUserError`` (has ``code``). Adapter handles
each per-mutation.

Pattern G: per-adapter Money handling (amount supplied as
numeric, formatted to 2-decimal string + currencyCode).
``orderCapture`` uses the legacy ``Money`` scalar type — a flat
string, not a MoneyInput dict — so the adapter passes the
numeric value as a formatted string and the currency separately.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_TRANSACTION_FIELDS = """
id
gateway
kind
status
processedAt
test
amountSet {
  shopMoney {
    amount
    currencyCode
  }
}
""".strip()


_ORDER_CAPTURE_MUTATION = f"""
mutation orderCapture($input: OrderCaptureInput!) {{
  orderCapture(input: $input) {{
    transaction {{
      {_TRANSACTION_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_TRANSACTION_VOID_MUTATION = f"""
mutation transactionVoid($parentTransactionId: ID!) {{
  transactionVoid(parentTransactionId: $parentTransactionId) {{
    transaction {{
      {_TRANSACTION_FIELDS}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


class ShopifyOrderPaymentAdapter(ShopifyBaseAdapter):
    name = "shopify_order_payment"
    capabilities = {
        Capability.SHOPIFY_CAPTURE_ORDER_PAYMENT,
        Capability.SHOPIFY_VOID_TRANSACTION,
    }
    required_scopes = frozenset({"read_orders", "write_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CAPTURE_ORDER_PAYMENT:
            return self._capture(params)
        if capability == Capability.SHOPIFY_VOID_TRANSACTION:
            return self._void(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Capture ────────────────────────────────────────────────────

    def _capture(self, params: dict[str, Any]) -> Any:
        input_dict = self._build_capture_input(params)
        data = self._gql(_ORDER_CAPTURE_MUTATION, {"input": input_dict})
        self._check_user_errors(data, "orderCapture")
        payload = data.get("orderCapture") or {}
        return self._success(
            Capability.SHOPIFY_CAPTURE_ORDER_PAYMENT,
            data={
                "transaction": self._normalise_transaction(
                    payload.get("transaction") or {}
                ),
            },
        )

    # ── Void ───────────────────────────────────────────────────────

    def _void(self, params: dict[str, Any]) -> Any:
        parent_id = (
            params.get("parent_transaction_id")
            or params.get("parentTransactionId")
            or params.get("id")
        )
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise AdapterValidationError(
                self.name,
                "'parent_transaction_id' (Shopify GID for the "
                "OrderTransaction to void) is required",
            )
        data = self._gql(_TRANSACTION_VOID_MUTATION, {
            "parentTransactionId": parent_id.strip(),
        })
        self._check_user_errors(data, "transactionVoid")
        payload = data.get("transactionVoid") or {}
        return self._success(
            Capability.SHOPIFY_VOID_TRANSACTION,
            data={
                "transaction": self._normalise_transaction(
                    payload.get("transaction") or {}
                ),
            },
        )

    # ── Input builders ─────────────────────────────────────────────

    def _build_capture_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        order_id = (
            params.get("order_id")
            or params.get("orderId")
            or params.get("id")
        )
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'order_id' (Shopify GID for the order) is required",
            )
        parent_id = (
            params.get("parent_transaction_id")
            or params.get("parentTransactionId")
        )
        if not isinstance(parent_id, str) or not parent_id.strip():
            raise AdapterValidationError(
                self.name,
                "'parent_transaction_id' (the authorisation transaction "
                "GID to capture against) is required",
            )
        amount = params.get("amount")
        if amount is None:
            raise AdapterValidationError(
                self.name,
                "'amount' is required (e.g. 19.99) — orderCapture's "
                "Money scalar takes a string amount",
            )
        try:
            amount_decimal = float(amount)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, "'amount' must be numeric",
            ) from exc
        if amount_decimal <= 0:
            raise AdapterValidationError(
                self.name, "'amount' must be > 0",
            )
        out: dict[str, Any] = {
            "id": order_id.strip(),
            "parentTransactionId": parent_id.strip(),
            "amount": f"{amount_decimal:.2f}",
        }
        currency = (
            params.get("currency")
            or params.get("currency_code")
            or params.get("currencyCode")
        )
        if currency is not None:
            if not isinstance(currency, str) or not currency.strip():
                raise AdapterValidationError(
                    self.name,
                    "'currency' must be a non-empty 3-letter ISO code",
                )
            out["currency"] = currency.strip().upper()

        final = params.get("final_capture")
        if final is None:
            final = params.get("finalCapture")
        if final is not None:
            out["finalCapture"] = bool(final)

        return out

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_money(node: Any) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {"amount": 0.0, "currency_code": ""}
        try:
            amount = float(node.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return {
            "amount": amount,
            "currency_code": node.get("currencyCode", "") or "",
        }

    @classmethod
    def _normalise_transaction(
        cls, node: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        amount_set = node.get("amountSet") or {}
        shop_money = (
            amount_set.get("shopMoney")
            if isinstance(amount_set, dict) else None
        ) or {}
        return {
            "id": node.get("id", "") or "",
            "gateway": node.get("gateway", "") or "",
            "kind": node.get("kind", "") or "",
            "status": node.get("status", "") or "",
            "processed_at": node.get("processedAt", "") or "",
            "test": bool(node.get("test", False)),
            "amount": cls._normalise_money(shop_money),
        }
