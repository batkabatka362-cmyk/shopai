"""ShopifyOrderInvoiceSendAdapter — email a paid-order invoice/receipt.

Companion to ``draft_order_invoice.py`` (which emails an unpaid
draft-order quote with a checkout link). The order-invoice surface
emails the receipt for an already-placed order — used for re-sends
when the customer claims they didn't get the original, or as part
of an audit/compliance flow that emails the merchant a copy.

Capability:

  * ``SHOPIFY_SEND_ORDER_INVOICE`` — re-send the paid-order invoice
    to the customer (or a custom recipient).

Friendly call shape mirrors draft_order_invoice for engine
consistency::

    {"order_id":       "gid://shopify/Order/123",
     "to":             "buyer@example.com",
     "from":           "sales@yourstore.com",
     "subject":        "Your receipt from ShopAI",
     "custom_message": "Replacement copy of your invoice.",
     "bcc":            ["sales@yourstore.com"]}

Pattern A: ``orderInvoiceSend`` takes the order GID at field level
+ an ``email`` Input. Same convention as
draftOrderInvoiceSend / orderClose.

Pattern F note: ``orderInvoiceSend.userErrors`` returns ``UserError``
(no ``code`` field), not ``UserErrors``. Same family as orderEdit /
draftOrderCalculate / draftOrderInvoice* (4 mutations, all
order-related, all bare UserError).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SEND_ORDER_INVOICE_MUTATION = """
mutation orderInvoiceSend($id: ID!, $email: EmailInput) {
  orderInvoiceSend(id: $id, email: $email) {
    order {
      id
      name
      email
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyOrderInvoiceSendAdapter(ShopifyBaseAdapter):
    name = "shopify_order_invoice"
    capabilities = {Capability.SHOPIFY_SEND_ORDER_INVOICE}
    required_scopes = frozenset({"write_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_SEND_ORDER_INVOICE:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        return self._send(params)

    # ── Send ──────────────────────────────────────────────────────

    def _send(self, params: dict[str, Any]) -> Any:
        order_id = params.get("order_id") or params.get("id") or params.get(
            "orderId"
        )
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'order_id' (Shopify GID for the order) is required",
            )
        email = self._build_email_input(params)
        variables: dict[str, Any] = {"id": order_id.strip()}
        if email:
            variables["email"] = email
        data = self._gql(_SEND_ORDER_INVOICE_MUTATION, variables)
        self._check_user_errors(data, "orderInvoiceSend")
        payload = data.get("orderInvoiceSend") or {}
        order = payload.get("order") or {}
        return self._success(
            Capability.SHOPIFY_SEND_ORDER_INVOICE,
            data={
                "order_id": order.get("id", "") or "",
                "order_name": order.get("name", "") or "",
                "email": order.get("email", "") or "",
            },
        )

    # ── Email input helper ────────────────────────────────────────

    def _build_email_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        to_addr = params.get("to") or params.get("toAddress")
        if to_addr is not None:
            if not isinstance(to_addr, str):
                raise AdapterValidationError(
                    self.name, "'to' must be a string",
                )
            out["to"] = to_addr.strip()

        from_addr = params.get("from") or params.get("fromAddress")
        if from_addr is not None:
            if not isinstance(from_addr, str):
                raise AdapterValidationError(
                    self.name, "'from' must be a string",
                )
            out["from"] = from_addr.strip()

        subject = params.get("subject")
        if subject is not None:
            if not isinstance(subject, str):
                raise AdapterValidationError(
                    self.name, "'subject' must be a string",
                )
            out["subject"] = subject

        custom_message = params.get("custom_message") or params.get(
            "customMessage"
        )
        if custom_message is not None:
            if not isinstance(custom_message, str):
                raise AdapterValidationError(
                    self.name, "'custom_message' must be a string",
                )
            out["customMessage"] = custom_message

        bcc = params.get("bcc")
        if bcc is not None:
            if isinstance(bcc, str):
                bcc = [b.strip() for b in bcc.split(",") if b.strip()]
            if not isinstance(bcc, list) or not all(
                isinstance(b, str) for b in bcc
            ):
                raise AdapterValidationError(
                    self.name,
                    "'bcc' must be a list of email strings or comma-separated",
                )
            out["bcc"] = bcc

        return out
