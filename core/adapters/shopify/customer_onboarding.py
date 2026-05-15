"""ShopifyCustomerOnboardingAdapter — account activation onboarding.

Companion to ``customers.py`` (CRUD) and
``customer_addresses.py`` (per-address writes). Both write paths
mint or update the customer record, but neither closes the
"account is now usable on the storefront" loop. Two related
mutations sit at that boundary:

  * ``customerGenerateAccountActivationUrl`` — returns a one-
    time URL the customer can click to set their password and
    activate the account. The engine pastes the URL into its
    own ESP template (Klaviyo, Customer.io, …) — useful when
    the merchant runs branded onboarding emails outside
    Shopify Email.
  * ``customerSendAccountInviteEmail`` — uses Shopify's built-
    in invite email template. The engine just triggers; the
    template, subject, and styling are merchant-side admin
    config.

ShopAI's onboarding engine picks one of the two depending on
whether the merchant has a custom email pipeline. Both pair
naturally with companyContactSendWelcomeEmail (B2B counterpart
in ``company_auxiliary.py``).

Capabilities:

  * ``SHOPIFY_GENERATE_CUSTOMER_ACTIVATION_URL`` —
    customerGenerateAccountActivationUrl. Pattern A:
    customerId at field level.
  * ``SHOPIFY_SEND_CUSTOMER_INVITE_EMAIL`` —
    customerSendAccountInviteEmail. Pattern A: customerId at
    field level; optional email overrides via EmailInput
    (subject/body/bcc/customMessage).

Pattern F: ``customerGenerateAccountActivationUrl`` userErrors
are typed ``UserError`` (no ``code``).
``customerSendAccountInviteEmail`` userErrors are typed
``CustomerSendAccountInviteEmailUserError`` (has ``code``).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_GENERATE_URL_MUTATION = """
mutation customerGenerateAccountActivationUrl($customerId: ID!) {
  customerGenerateAccountActivationUrl(customerId: $customerId) {
    accountActivationUrl
    userErrors {
      field
      message
    }
  }
}
""".strip()


_SEND_INVITE_EMAIL_MUTATION = """
mutation customerSendAccountInviteEmail(
  $customerId: ID!,
  $email: EmailInput
) {
  customerSendAccountInviteEmail(
    customerId: $customerId, email: $email
  ) {
    customer {
      id
      email
      state
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyCustomerOnboardingAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_onboarding"
    capabilities = {
        Capability.SHOPIFY_GENERATE_CUSTOMER_ACTIVATION_URL,
        Capability.SHOPIFY_SEND_CUSTOMER_INVITE_EMAIL,
    }
    required_scopes = frozenset({"write_customers"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_GENERATE_CUSTOMER_ACTIVATION_URL:
            return self._generate_url(params)
        if capability == Capability.SHOPIFY_SEND_CUSTOMER_INVITE_EMAIL:
            return self._send_invite(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Generate URL ───────────────────────────────────────────────

    def _generate_url(self, params: dict[str, Any]) -> Any:
        customer_id = self._extract_customer_id(params)
        data = self._gql(_GENERATE_URL_MUTATION, {
            "customerId": customer_id,
        })
        self._check_user_errors(
            data, "customerGenerateAccountActivationUrl",
        )
        payload = data.get(
            "customerGenerateAccountActivationUrl"
        ) or {}
        return self._success(
            Capability.SHOPIFY_GENERATE_CUSTOMER_ACTIVATION_URL,
            data={
                "activation_url": (
                    payload.get("accountActivationUrl", "") or ""
                ),
            },
        )

    # ── Send invite email ──────────────────────────────────────────

    def _send_invite(self, params: dict[str, Any]) -> Any:
        customer_id = self._extract_customer_id(params)

        variables: dict[str, Any] = {
            "customerId": customer_id,
            "email": None,
        }
        email_raw = params.get("email")
        if isinstance(email_raw, dict):
            variables["email"] = self._build_email_input(email_raw)

        data = self._gql(_SEND_INVITE_EMAIL_MUTATION, variables)
        self._check_user_errors(data, "customerSendAccountInviteEmail")
        payload = data.get("customerSendAccountInviteEmail") or {}
        customer = payload.get("customer") or {}
        return self._success(
            Capability.SHOPIFY_SEND_CUSTOMER_INVITE_EMAIL,
            data={
                "customer_id": (
                    customer.get("id", "")
                    if isinstance(customer, dict) else ""
                ) or "",
                "email": (
                    customer.get("email", "")
                    if isinstance(customer, dict) else ""
                ) or "",
                "state": (
                    customer.get("state", "")
                    if isinstance(customer, dict) else ""
                ) or "",
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_customer_id(self, params: dict[str, Any]) -> str:
        customer_id = (
            params.get("customer_id")
            or params.get("customerId")
            or params.get("id")
        )
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'customer_id' (Shopify GID for the customer) is required",
            )
        return customer_id.strip()

    def _build_email_input(self, raw: dict[str, Any]) -> dict[str, Any]:
        # Shared shape with company_auxiliary.py — kept inline rather
        # than imported because the adapters validate against their
        # own name in error messages.
        out: dict[str, Any] = {}
        for friendly, camel in (
            ("subject", "subject"),
            ("to", "to"),
            ("from_", "from"),
            ("from", "from"),
            ("body", "body"),
            ("custom_message", "customMessage"),
            ("customMessage", "customMessage"),
        ):
            if friendly in raw and raw[friendly] is not None:
                v = raw[friendly]
                if not isinstance(v, str):
                    raise AdapterValidationError(
                        self.name,
                        f"'email.{friendly}' must be a string",
                    )
                out[camel] = v

        bcc = raw.get("bcc")
        if bcc is not None:
            if isinstance(bcc, str):
                bcc = [bcc]
            if not isinstance(bcc, list) or not all(
                isinstance(b, str) for b in bcc
            ):
                raise AdapterValidationError(
                    self.name,
                    "'email.bcc' must be a list of strings",
                )
            out["bcc"] = [b.strip() for b in bcc if b.strip()]
        return out
