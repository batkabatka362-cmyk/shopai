"""ShopifyCustomerPaymentMethodOpsAdapter — payment-method UX flows.

Companion to ``customer_payment_methods.py`` (LIST / GET / REVOKE).
That adapter handles the mechanical CRUD on vaulted methods; this
one handles the two customer-facing UX paths Shopify exposes for
recovering an expired card without revoking-and-recreating:

  * **Send a Shopify-hosted "update your card" email.** When the
    subscription engine sees a card that's about to expire, it
    fires ``customerPaymentMethodSendUpdateEmail`` — Shopify
    composes and delivers the email to the customer, who clicks
    a one-time link, updates the card, and the existing payment
    method id stays valid (no contract re-link required).
  * **Get the update URL directly.** For embedded flows (the
    operator's own customer portal, recovery campaigns through
    a third-party email provider), the engine grabs the same
    one-time URL via ``customerPaymentMethodGetUpdateUrl`` and
    embeds it itself.

Capabilities:

  * ``SHOPIFY_SEND_PAYMENT_METHOD_UPDATE_EMAIL`` —
    customerPaymentMethodSendUpdateEmail. Pattern A:
    customerPaymentMethodId at field level. Optional ``email``
    EmailInput overrides the customer's default email.
  * ``SHOPIFY_GET_PAYMENT_METHOD_UPDATE_URL`` —
    customerPaymentMethodGetUpdateUrl. Pattern A:
    customerPaymentMethodId at field level. Returns a
    one-time URL the merchant embeds anywhere.

UserError variants:
  * Send + Revoke share the bare ``UserError`` type (no ``code``).
  * GetUpdateUrl uses ``CustomerPaymentMethodGetUpdateUrlUserError``
    (has ``code``).

Pattern F applies per-mutation — drop the ``code`` selection on
Send, keep it on GetUpdateUrl.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SEND_UPDATE_EMAIL_MUTATION = """
mutation customerPaymentMethodSendUpdateEmail(
  $customerPaymentMethodId: ID!,
  $email: EmailInput
) {
  customerPaymentMethodSendUpdateEmail(
    customerPaymentMethodId: $customerPaymentMethodId,
    email: $email
  ) {
    customer {
      id
      email
      displayName
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_GET_UPDATE_URL_MUTATION = """
mutation customerPaymentMethodGetUpdateUrl(
  $customerPaymentMethodId: ID!
) {
  customerPaymentMethodGetUpdateUrl(
    customerPaymentMethodId: $customerPaymentMethodId
  ) {
    updatePaymentMethodUrl
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyCustomerPaymentMethodOpsAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_payment_method_ops"
    capabilities = {
        Capability.SHOPIFY_SEND_PAYMENT_METHOD_UPDATE_EMAIL,
        Capability.SHOPIFY_GET_PAYMENT_METHOD_UPDATE_URL,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_SEND_PAYMENT_METHOD_UPDATE_EMAIL:
            return self._send_update_email(params)
        if capability == \
                Capability.SHOPIFY_GET_PAYMENT_METHOD_UPDATE_URL:
            return self._get_update_url(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Send update email ──────────────────────────────────────────

    def _send_update_email(self, params: dict[str, Any]) -> Any:
        method_id = self._extract_method_id(params)
        email = self._build_email_input(params)
        variables: dict[str, Any] = {
            "customerPaymentMethodId": method_id,
        }
        if email is not None:
            variables["email"] = email
        else:
            variables["email"] = None

        data = self._gql(_SEND_UPDATE_EMAIL_MUTATION, variables)
        self._check_user_errors(data, "customerPaymentMethodSendUpdateEmail")
        payload = data.get("customerPaymentMethodSendUpdateEmail") or {}
        customer = payload.get("customer") or {}
        return self._success(
            Capability.SHOPIFY_SEND_PAYMENT_METHOD_UPDATE_EMAIL,
            data={
                "customer_id": (
                    customer.get("id", "")
                    if isinstance(customer, dict) else ""
                ) or "",
                "customer_email": (
                    customer.get("email", "")
                    if isinstance(customer, dict) else ""
                ) or "",
                "customer_display_name": (
                    customer.get("displayName", "")
                    if isinstance(customer, dict) else ""
                ) or "",
                "email_override": (
                    email.get("emailAddress", "") if email else ""
                ),
            },
        )

    # ── Get update URL ─────────────────────────────────────────────

    def _get_update_url(self, params: dict[str, Any]) -> Any:
        method_id = self._extract_method_id(params)
        data = self._gql(_GET_UPDATE_URL_MUTATION, {
            "customerPaymentMethodId": method_id,
        })
        self._check_user_errors(data, "customerPaymentMethodGetUpdateUrl")
        payload = data.get("customerPaymentMethodGetUpdateUrl") or {}
        return self._success(
            Capability.SHOPIFY_GET_PAYMENT_METHOD_UPDATE_URL,
            data={
                "update_url": (
                    payload.get("updatePaymentMethodUrl", "") or ""
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_method_id(self, params: dict[str, Any]) -> str:
        method_id = (
            params.get("id")
            or params.get("payment_method_id")
            or params.get("customer_payment_method_id")
            or params.get("customerPaymentMethodId")
        )
        if not isinstance(method_id, str) or not method_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the customer payment method) "
                "is required",
            )
        return method_id.strip()

    def _build_email_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any] | None:
        # Friendly: caller may pass `email` as a plain string
        # (the override address) OR a full {emailAddress, ...} dict.
        # Omitted → Shopify uses the customer's default email.
        raw = params.get("email")
        if raw is None or raw == "":
            return None
        if isinstance(raw, str):
            email_addr = raw.strip()
            if not email_addr:
                return None
            return {"emailAddress": email_addr}
        if isinstance(raw, dict):
            email_addr = (
                raw.get("emailAddress")
                or raw.get("email_address")
                or raw.get("email")
            )
            if not isinstance(email_addr, str) or not email_addr.strip():
                raise AdapterValidationError(
                    self.name,
                    "'email' dict must have a non-empty 'emailAddress'",
                )
            out: dict[str, Any] = {"emailAddress": email_addr.strip()}
            subject = raw.get("subject")
            if isinstance(subject, str) and subject.strip():
                out["subject"] = subject.strip()
            body = raw.get("body") or raw.get("customMessage")
            if isinstance(body, str) and body.strip():
                out["customMessage"] = body.strip()
            return out
        raise AdapterValidationError(
            self.name,
            "'email' must be a string (address) or {emailAddress} dict",
        )
