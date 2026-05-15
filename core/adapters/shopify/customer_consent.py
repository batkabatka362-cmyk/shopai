"""ShopifyCustomerConsentAdapter — SMS / email marketing consent.

Companion to ``customers.py`` (general CRUD). The marketing-consent
mutations are split out here because they have a richer Input
surface (consent state machine + opt-in level + collected-from
attribution) and engines need to wire them into compliance flows
that the bare customer update path doesn't cover.

ShopAI's marketing engine uses these to:

  * Honour double-opt-in flows for new SMS subscribers (CONFIRMED →
    SUBSCRIBED only after the customer texts back YES).
  * Process unsubscribe webhooks (UNSUBSCRIBED with REVOKED reason).
  * Migrate consent records from a third-party ESP into Shopify's
    native subscriber list during a platform consolidation.

Capabilities:

  * ``SHOPIFY_UPDATE_SMS_CONSENT``    — set SMS marketing state
    (SUBSCRIBED / UNSUBSCRIBED / PENDING / NOT_SUBSCRIBED) and
    opt-in level (SINGLE_OPT_IN / CONFIRMED_OPT_IN /
    UNKNOWN).
  * ``SHOPIFY_UPDATE_EMAIL_CONSENT``  — same shape for email.

Friendly call shape::

    {"customer_id": "gid://shopify/Customer/123",
     "marketing_state": "SUBSCRIBED",
     "marketing_opt_in_level": "CONFIRMED_OPT_IN",
     "consent_collected_from": "SHOPIFY",   # or OTHER
     "consent_updated_at": "2026-04-26T10:00:00Z"}

Pattern A: both mutations take ``customerId`` at the field level
plus a structured ``smsMarketingConsent`` / ``emailMarketingConsent``
input. Same convention as customerMerge.

Pattern E note: gated by ``write_customers`` scope. SMS consent
also requires the merchant to have the Shopify Email/SMS or a
similar marketing app installed — the underlying mutation succeeds
either way but storefront delivery requires the channel.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_SMS_CONSENT_MUTATION = """
mutation customerSmsMarketingConsentUpdate(
  $input: CustomerSmsMarketingConsentUpdateInput!
) {
  customerSmsMarketingConsentUpdate(input: $input) {
    customer {
      id
      phone
      smsMarketingConsent {
        marketingState
        marketingOptInLevel
        consentCollectedFrom
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


_EMAIL_CONSENT_MUTATION = """
mutation customerEmailMarketingConsentUpdate(
  $input: CustomerEmailMarketingConsentUpdateInput!
) {
  customerEmailMarketingConsentUpdate(input: $input) {
    customer {
      id
      email
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


_VALID_MARKETING_STATES = {
    "NOT_SUBSCRIBED", "PENDING", "SUBSCRIBED", "UNSUBSCRIBED", "REDACTED",
}

_VALID_OPT_IN_LEVELS = {
    "SINGLE_OPT_IN", "CONFIRMED_OPT_IN", "UNKNOWN",
}

_VALID_CONSENT_SOURCES = {"SHOPIFY", "OTHER"}


class ShopifyCustomerConsentAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_consent"
    capabilities = {
        Capability.SHOPIFY_UPDATE_SMS_CONSENT,
        Capability.SHOPIFY_UPDATE_EMAIL_CONSENT,
    }
    required_scopes = frozenset({
        "read_customers", "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_UPDATE_SMS_CONSENT:
            return self._update_sms(params)
        if capability == Capability.SHOPIFY_UPDATE_EMAIL_CONSENT:
            return self._update_email(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── SMS ────────────────────────────────────────────────────────

    def _update_sms(self, params: dict[str, Any]) -> Any:
        consent_input = self._build_input(params, sms=True)
        data = self._gql(_SMS_CONSENT_MUTATION, {"input": consent_input})
        self._check_user_errors(
            data, "customerSmsMarketingConsentUpdate",
        )
        payload = data.get("customerSmsMarketingConsentUpdate") or {}
        customer = payload.get("customer") or {}
        consent = customer.get("smsMarketingConsent") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_SMS_CONSENT,
            data={
                "customer_id": customer.get("id", "") or "",
                "phone": customer.get("phone", "") or "",
                "marketing_state": (
                    consent.get("marketingState", "")
                    if isinstance(consent, dict) else ""
                ) or "",
                "marketing_opt_in_level": (
                    consent.get("marketingOptInLevel", "")
                    if isinstance(consent, dict) else ""
                ) or "",
                "consent_collected_from": (
                    consent.get("consentCollectedFrom", "")
                    if isinstance(consent, dict) else ""
                ) or "",
                "consent_updated_at": (
                    consent.get("consentUpdatedAt", "")
                    if isinstance(consent, dict) else ""
                ) or "",
            },
        )

    # ── Email ──────────────────────────────────────────────────────

    def _update_email(self, params: dict[str, Any]) -> Any:
        consent_input = self._build_input(params, sms=False)
        data = self._gql(_EMAIL_CONSENT_MUTATION, {"input": consent_input})
        self._check_user_errors(
            data, "customerEmailMarketingConsentUpdate",
        )
        payload = data.get("customerEmailMarketingConsentUpdate") or {}
        customer = payload.get("customer") or {}
        consent = customer.get("emailMarketingConsent") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_EMAIL_CONSENT,
            data={
                "customer_id": customer.get("id", "") or "",
                "email": customer.get("email", "") or "",
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
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_input(
        self, params: dict[str, Any], sms: bool,
    ) -> dict[str, Any]:
        customer_id = params.get("customer_id") or params.get("customerId")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'customer_id' (Shopify GID for the customer) is required",
            )

        state = params.get("marketing_state") or params.get("marketingState")
        if not isinstance(state, str) or state.upper() not in _VALID_MARKETING_STATES:
            raise AdapterValidationError(
                self.name,
                f"'marketing_state' is required and must be one of: "
                f"{sorted(_VALID_MARKETING_STATES)}",
            )

        consent: dict[str, Any] = {"marketingState": state.upper()}

        opt_in = params.get("marketing_opt_in_level") or params.get(
            "marketingOptInLevel"
        )
        if opt_in is not None:
            if not isinstance(opt_in, str) or opt_in.upper() not in _VALID_OPT_IN_LEVELS:
                raise AdapterValidationError(
                    self.name,
                    f"'marketing_opt_in_level' must be one of: "
                    f"{sorted(_VALID_OPT_IN_LEVELS)}",
                )
            consent["marketingOptInLevel"] = opt_in.upper()

        updated_at = params.get("consent_updated_at") or params.get(
            "consentUpdatedAt"
        )
        if updated_at is not None:
            if not isinstance(updated_at, str):
                raise AdapterValidationError(
                    self.name,
                    "'consent_updated_at' must be ISO-8601 string",
                )
            consent["consentUpdatedAt"] = updated_at.strip()

        # consentCollectedFrom is SMS-only — email's input shape
        # doesn't include it.
        if sms:
            collected_from = params.get("consent_collected_from") or params.get(
                "consentCollectedFrom"
            )
            if collected_from is not None:
                if (
                    not isinstance(collected_from, str)
                    or collected_from.upper() not in _VALID_CONSENT_SOURCES
                ):
                    raise AdapterValidationError(
                        self.name,
                        f"'consent_collected_from' must be one of: "
                        f"{sorted(_VALID_CONSENT_SOURCES)}",
                    )
                consent["consentCollectedFrom"] = collected_from.upper()

        consent_field = (
            "smsMarketingConsent" if sms else "emailMarketingConsent"
        )
        return {
            "customerId": customer_id.strip(),
            consent_field: consent,
        }
