"""ShopifyCustomerMarketingAdapter — consent + account-invite ops.

Three customer-facing marketing/communication mutations that didn't
fit any existing adapter:

  * **Email marketing consent.** ``customerEmailMarketingConsentUpdate``
    flips a customer's email-marketing-state SUBSCRIBED ↔ PENDING ↔
    UNSUBSCRIBED, with the regulator-tracked ``consentUpdatedAt`` and
    ``sourceLocationId`` evidence trail. ShopAI's outreach engine uses
    this whenever a customer opts in via a checkout extension or
    landing page so the official record is consistent across
    Klaviyo / Mailchimp and Shopify's customer record.
  * **SMS marketing consent.** ``customerSmsMarketingConsentUpdate``
    is the same flow for SMS — distinct mutation because TCPA /
    PECR have different evidence requirements than CAN-SPAM.
  * **Account invite email.** ``customerSendAccountInviteEmail``
    re-sends the "create your account" email — used by the
    onboarding engine when a customer signed up at checkout but
    never set a password, or when the merchant migrates from a
    different storefront and wants to invite all existing
    customers to claim their accounts.

Capabilities:

  * ``SHOPIFY_UPDATE_CUSTOMER_EMAIL_MARKETING_CONSENT``
  * ``SHOPIFY_UPDATE_CUSTOMER_SMS_MARKETING_CONSENT``
  * ``SHOPIFY_SEND_CUSTOMER_ACCOUNT_INVITE``

Pattern C confirmed live: ``NOT_SUBSCRIBED`` is a read-only state
on input — Shopify rejects it with "Cannot specify NOT_SUBSCRIBED
as a marketing state input". Adapter restricts the input enum
client-side to PENDING / SUBSCRIBED / UNSUBSCRIBED / REDACTED /
INVALID.

Pattern F: all three mutations carry the ``code`` field on their
userErrors (probed live: INVALID came back on synthetic-customer
calls). Selection keeps it.

Pattern E note: gated by ``write_customers``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_EMAIL_CONSENT_MUTATION = """
mutation customerEmailMarketingConsentUpdate(
  $input: CustomerEmailMarketingConsentUpdateInput!
) {
  customerEmailMarketingConsentUpdate(input: $input) {
    customer {
      id
      email
      displayName
      emailMarketingConsent {
        marketingState
        marketingOptInLevel
        consentUpdatedAt
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_SMS_CONSENT_MUTATION = """
mutation customerSmsMarketingConsentUpdate(
  $input: CustomerSmsMarketingConsentUpdateInput!
) {
  customerSmsMarketingConsentUpdate(input: $input) {
    customer {
      id
      phone
      displayName
      smsMarketingConsent {
        marketingState
        marketingOptInLevel
        consentUpdatedAt
      }
    }
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_INVITE_MUTATION = """
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
      displayName
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


# Pattern C: NOT_SUBSCRIBED is read-only on input.
_VALID_EMAIL_STATES = {
    "PENDING", "SUBSCRIBED", "UNSUBSCRIBED", "REDACTED", "INVALID",
}
_VALID_SMS_STATES = {
    "PENDING", "SUBSCRIBED", "UNSUBSCRIBED", "REDACTED",
}
_VALID_OPT_IN_LEVELS = {
    "SINGLE_OPT_IN", "CONFIRMED_OPT_IN", "UNKNOWN",
}


class ShopifyCustomerMarketingAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_marketing"
    capabilities = {
        Capability.SHOPIFY_UPDATE_CUSTOMER_EMAIL_MARKETING_CONSENT,
        Capability.SHOPIFY_UPDATE_CUSTOMER_SMS_MARKETING_CONSENT,
        Capability.SHOPIFY_SEND_CUSTOMER_ACCOUNT_INVITE,
    }
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_UPDATE_CUSTOMER_EMAIL_MARKETING_CONSENT:
            return self._email_consent(params)
        if capability == \
                Capability.SHOPIFY_UPDATE_CUSTOMER_SMS_MARKETING_CONSENT:
            return self._sms_consent(params)
        if capability == Capability.SHOPIFY_SEND_CUSTOMER_ACCOUNT_INVITE:
            return self._send_invite(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Email consent ──────────────────────────────────────────────

    def _email_consent(self, params: dict[str, Any]) -> Any:
        customer_id = self._extract_customer_id(params)
        consent = self._build_consent(
            params, _VALID_EMAIL_STATES, "email",
        )
        body = {
            "customerId": customer_id,
            "emailMarketingConsent": consent,
        }
        data = self._gql(_EMAIL_CONSENT_MUTATION, {"input": body})
        self._check_user_errors(data, "customerEmailMarketingConsentUpdate")
        payload = data.get("customerEmailMarketingConsentUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CUSTOMER_EMAIL_MARKETING_CONSENT,
            data={
                "customer": self._normalise_customer(
                    payload.get("customer") or {},
                    consent_key="emailMarketingConsent",
                    contact_key="email",
                ),
            },
        )

    # ── SMS consent ────────────────────────────────────────────────

    def _sms_consent(self, params: dict[str, Any]) -> Any:
        customer_id = self._extract_customer_id(params)
        consent = self._build_consent(
            params, _VALID_SMS_STATES, "sms",
        )
        body = {
            "customerId": customer_id,
            "smsMarketingConsent": consent,
        }
        data = self._gql(_SMS_CONSENT_MUTATION, {"input": body})
        self._check_user_errors(data, "customerSmsMarketingConsentUpdate")
        payload = data.get("customerSmsMarketingConsentUpdate") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_CUSTOMER_SMS_MARKETING_CONSENT,
            data={
                "customer": self._normalise_customer(
                    payload.get("customer") or {},
                    consent_key="smsMarketingConsent",
                    contact_key="phone",
                ),
            },
        )

    # ── Account invite ─────────────────────────────────────────────

    def _send_invite(self, params: dict[str, Any]) -> Any:
        customer_id = self._extract_customer_id(params)
        email_override = self._build_email_override(params)
        variables: dict[str, Any] = {"customerId": customer_id}
        variables["email"] = email_override
        data = self._gql(_INVITE_MUTATION, variables)
        self._check_user_errors(data, "customerSendAccountInviteEmail")
        payload = data.get("customerSendAccountInviteEmail") or {}
        customer = payload.get("customer") or {}
        return self._success(
            Capability.SHOPIFY_SEND_CUSTOMER_ACCOUNT_INVITE,
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
                "state": (
                    customer.get("state", "")
                    if isinstance(customer, dict) else ""
                ) or "",
                "email_override_address": (
                    email_override.get("to", "")
                    if email_override else ""
                ),
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
                "'customer_id' (Shopify GID for the customer) "
                "is required",
            )
        return customer_id.strip()

    def _build_consent(
        self,
        params: dict[str, Any],
        valid_states: set[str],
        kind: str,
    ) -> dict[str, Any]:
        state_raw = (
            params.get("marketing_state")
            or params.get("marketingState")
            or params.get("state")
        )
        if not isinstance(state_raw, str) or not state_raw.strip():
            raise AdapterValidationError(
                self.name,
                f"'marketing_state' is required (one of "
                f"{sorted(valid_states)})",
            )
        state = state_raw.strip().upper()
        if state not in valid_states:
            raise AdapterValidationError(
                self.name,
                f"'marketing_state' for {kind} consent must be one of "
                f"{sorted(valid_states)} — Shopify rejects "
                f"NOT_SUBSCRIBED as a write input (read-only state)",
            )

        opt_in_raw = (
            params.get("marketing_opt_in_level")
            or params.get("marketingOptInLevel")
            or params.get("opt_in_level")
        )
        out: dict[str, Any] = {"marketingState": state}
        if opt_in_raw is not None:
            if not isinstance(opt_in_raw, str):
                raise AdapterValidationError(
                    self.name,
                    "'marketing_opt_in_level' must be a string",
                )
            opt_in = opt_in_raw.strip().upper()
            if opt_in not in _VALID_OPT_IN_LEVELS:
                raise AdapterValidationError(
                    self.name,
                    f"'marketing_opt_in_level' must be one of "
                    f"{sorted(_VALID_OPT_IN_LEVELS)}",
                )
            out["marketingOptInLevel"] = opt_in

        consent_at = (
            params.get("consent_updated_at")
            or params.get("consentUpdatedAt")
        )
        if consent_at is not None:
            if not isinstance(consent_at, str) or not consent_at.strip():
                raise AdapterValidationError(
                    self.name,
                    "'consent_updated_at' must be an ISO datetime string",
                )
            out["consentUpdatedAt"] = consent_at.strip()

        source_location_id = (
            params.get("source_location_id")
            or params.get("sourceLocationId")
        )
        if source_location_id is not None:
            if not isinstance(source_location_id, str) or \
                    not source_location_id.strip():
                raise AdapterValidationError(
                    self.name,
                    "'source_location_id' must be a Shopify Location GID",
                )
            out["sourceLocationId"] = source_location_id.strip()

        return out

    def _build_email_override(
        self, params: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw = params.get("email")
        if raw is None or raw == "":
            return None
        if isinstance(raw, str):
            address = raw.strip()
            if not address:
                return None
            return {"to": address}
        if isinstance(raw, dict):
            address = (
                raw.get("to")
                or raw.get("emailAddress")
                or raw.get("email_address")
                or raw.get("email")
            )
            if not isinstance(address, str) or not address.strip():
                raise AdapterValidationError(
                    self.name,
                    "'email' dict must include 'to' (the override "
                    "address)",
                )
            out: dict[str, Any] = {"to": address.strip()}
            for snake, camel in (
                ("subject", "subject"),
                ("from", "from"),
                ("from_address", "from"),
                ("body", "body"),
                ("custom_message", "customMessage"),
            ):
                v = raw.get(snake)
                if isinstance(v, str) and v.strip():
                    out[camel] = v.strip()
            bcc = raw.get("bcc")
            if isinstance(bcc, list):
                cleaned = [
                    b.strip() for b in bcc
                    if isinstance(b, str) and b.strip()
                ]
                if cleaned:
                    out["bcc"] = cleaned
            return out
        raise AdapterValidationError(
            self.name,
            "'email' must be a string (address) or {to, ...} dict",
        )

    @staticmethod
    def _normalise_customer(
        node: dict[str, Any],
        *,
        consent_key: str,
        contact_key: str,
    ) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        consent = node.get(consent_key) or {}
        return {
            "id": node.get("id", "") or "",
            contact_key: node.get(contact_key, "") or "",
            "display_name": node.get("displayName", "") or "",
            "marketing_state": (
                consent.get("marketingState", "")
                if isinstance(consent, dict) else ""
            ) or "",
            "marketing_opt_in_level": (
                consent.get("marketingOptInLevel", "")
                if isinstance(consent, dict) else ""
            ) or "",
            "consent_updated_at": (
                consent.get("consentUpdatedAt", "")
                if isinstance(consent, dict) else ""
            ) or "",
        }
