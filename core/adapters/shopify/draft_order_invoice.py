"""ShopifyDraftOrderInvoiceSendAdapter — email customer invoice flows.

Companion to ``draft_orders.py`` (which CRUDs draft orders).
The invoice flow lets the merchant (or ShopAI's sales engine) email
a customer a checkout link for a pending draft order — common B2B
flow ("here's your quote, click to pay") and a recovery flow for
abandoned-cart funnels.

Capabilities:

  * ``SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE`` — fetch the rendered
    HTML body that would be sent (no email actually fires). Engines
    use this to QA the invoice template before triggering the send.
  * ``SHOPIFY_SEND_DRAFT_ORDER_INVOICE``    — actually send the
    invoice email through Shopify's mailer.

Friendly call shape (mirrors Shopify's EmailInput)::

    {"draft_order_id": "gid://shopify/DraftOrder/123",
     "to":             "buyer@example.com",
     "from":           "sales@yourstore.com",
     "subject":        "Your quote from ShopAI",
     "custom_message": "Reply with any questions.",
     "bcc":            ["sales@yourstore.com"]}

Pattern A: both mutations take the draft-order GID as a top-level
``id`` argument PLUS an optional ``email`` Input — the GID is NOT
inside the input. Same convention as orderClose / themeFilesUpsert.

Pattern E note: gated by ``write_draft_orders`` scope. Send is a
real outbound email — the test suite mocks _gql to verify the wire
shape, but live verification on a real customer is intentionally
NOT executed (would spam the merchant inbox).

Pattern F note (per CLAUDE.md): both ``draftOrderInvoicePreview``
and ``draftOrderInvoiceSend`` return ``UserError`` (no ``code``
field), not ``UserErrors``. Same as orderEdit / draftOrderCalculate.
Asking for ``code`` rejects the whole query at validation.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_PREVIEW_DRAFT_ORDER_INVOICE_MUTATION = """
mutation draftOrderInvoicePreview($id: ID!, $email: EmailInput) {
  draftOrderInvoicePreview(id: $id, email: $email) {
    previewSubject
    previewHtml
    userErrors {
      field
      message
    }
  }
}
""".strip()


_SEND_DRAFT_ORDER_INVOICE_MUTATION = """
mutation draftOrderInvoiceSend($id: ID!, $email: EmailInput) {
  draftOrderInvoiceSend(id: $id, email: $email) {
    draftOrder {
      id
      name
      status
      invoiceSentAt
      invoiceUrl
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


class ShopifyDraftOrderInvoiceSendAdapter(ShopifyBaseAdapter):
    name = "shopify_draft_order_invoice"
    capabilities = {
        Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE,
        Capability.SHOPIFY_SEND_DRAFT_ORDER_INVOICE,
    }
    required_scopes = frozenset({"write_draft_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE:
            return self._preview(params)
        if capability == Capability.SHOPIFY_SEND_DRAFT_ORDER_INVOICE:
            return self._send(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Preview ────────────────────────────────────────────────────

    def _preview(self, params: dict[str, Any]) -> Any:
        draft_id = self._require_draft_order_id(params)
        email = self._build_email_input(params)
        variables: dict[str, Any] = {"id": draft_id}
        if email:
            variables["email"] = email
        data = self._gql(_PREVIEW_DRAFT_ORDER_INVOICE_MUTATION, variables)
        self._check_user_errors(data, "draftOrderInvoicePreview")
        payload = data.get("draftOrderInvoicePreview") or {}
        return self._success(
            Capability.SHOPIFY_PREVIEW_DRAFT_ORDER_INVOICE,
            data={
                "subject": payload.get("previewSubject", "") or "",
                "html": payload.get("previewHtml", "") or "",
            },
        )

    # ── Send ──────────────────────────────────────────────────────

    def _send(self, params: dict[str, Any]) -> Any:
        draft_id = self._require_draft_order_id(params)
        email = self._build_email_input(params)
        variables: dict[str, Any] = {"id": draft_id}
        if email:
            variables["email"] = email
        data = self._gql(_SEND_DRAFT_ORDER_INVOICE_MUTATION, variables)
        self._check_user_errors(data, "draftOrderInvoiceSend")
        payload = data.get("draftOrderInvoiceSend") or {}
        order = payload.get("draftOrder") or {}
        return self._success(
            Capability.SHOPIFY_SEND_DRAFT_ORDER_INVOICE,
            data={
                "draft_order_id": order.get("id", "") or "",
                "draft_order_name": order.get("name", "") or "",
                "status": order.get("status", "") or "",
                "invoice_sent_at": order.get("invoiceSentAt", "") or "",
                "invoice_url": order.get("invoiceUrl", "") or "",
            },
        )

    # ── Input helpers ──────────────────────────────────────────────

    def _require_draft_order_id(self, params: dict[str, Any]) -> str:
        draft_id = params.get("draft_order_id") or params.get("id") or params.get(
            "draftOrderId"
        )
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise AdapterValidationError(
                self.name,
                "'draft_order_id' (Shopify GID for the draft order) is required",
            )
        return draft_id.strip()

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
                    "'bcc' must be a list of email strings or comma-separated string",
                )
            out["bcc"] = bcc

        return out
