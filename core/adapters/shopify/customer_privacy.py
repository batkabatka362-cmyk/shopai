"""ShopifyCustomerPrivacyAdapter — GDPR + CCPA compliance mutations.

When a customer exercises a regulator-granted privacy right, the
merchant has to act through Shopify's first-party flow (so the action
ripples through their CDN, vault, log retention, and downstream
integrations) rather than just deleting the row in Postgres. Two
distinct rights:

  * **Right to erasure (GDPR Art. 17 / EU UK).** The customer asks
    for all their personal data to be deleted from the merchant's
    systems. ``customerRequestDataErasure`` queues the deletion —
    Shopify processes it asynchronously, scrubs PII, and replaces
    the customer's email/phone with redacted placeholders. ShopAI's
    privacy engine fires this whenever a customer-support flow
    receives a confirmed erasure request.
  * **Do-not-sell-or-share (CCPA / CPRA — California).** The
    customer asks the merchant not to sell or share their data
    with third parties. ``dataSaleOptOut`` is keyed by EMAIL (not
    customer GID — the request can come from someone who isn't
    yet a registered customer in the shop), and Shopify flags the
    record so downstream marketing integrations skip it.

Capabilities:

  * ``SHOPIFY_REQUEST_CUSTOMER_DATA_ERASURE`` —
    customerRequestDataErasure. Pattern A: customerId at field level.
  * ``SHOPIFY_DATA_SALE_OPT_OUT`` — dataSaleOptOut. Email at field
    level (NOT customerId — important: any email, not just registered
    customers, can opt out under CCPA).

Pattern F: both userError types
(``CustomerRequestDataErasureUserError``,
``DataSaleOptOutUserError``) carry the ``code`` field —
introspection confirmed.

Pattern E note: gated by ``write_customers``. The erasure flow may
also depend on the merchant's data-retention configuration; the API
queues the request even if processing is asynchronous, so the
adapter just surfaces the queued customer id back to the caller.
"""
from __future__ import annotations

import re
from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_REQUEST_ERASURE_MUTATION = """
mutation customerRequestDataErasure($customerId: ID!) {
  customerRequestDataErasure(customerId: $customerId) {
    customerId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_DATA_SALE_OPT_OUT_MUTATION = """
mutation dataSaleOptOut($email: String!) {
  dataSaleOptOut(email: $email) {
    customerId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ShopifyCustomerPrivacyAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_privacy"
    capabilities = {
        Capability.SHOPIFY_REQUEST_CUSTOMER_DATA_ERASURE,
        Capability.SHOPIFY_DATA_SALE_OPT_OUT,
    }
    required_scopes = frozenset({"write_customers"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_REQUEST_CUSTOMER_DATA_ERASURE:
            return self._request_erasure(params)
        if capability == Capability.SHOPIFY_DATA_SALE_OPT_OUT:
            return self._data_sale_opt_out(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Erasure ────────────────────────────────────────────────────

    def _request_erasure(self, params: dict[str, Any]) -> Any:
        customer_id = (
            params.get("customer_id")
            or params.get("customerId")
            or params.get("id")
        )
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'customer_id' (Shopify GID for the customer to erase) "
                "is required",
            )

        data = self._gql(_REQUEST_ERASURE_MUTATION, {
            "customerId": customer_id.strip(),
        })
        self._check_user_errors(data, "customerRequestDataErasure")
        payload = data.get("customerRequestDataErasure") or {}
        return self._success(
            Capability.SHOPIFY_REQUEST_CUSTOMER_DATA_ERASURE,
            data={
                "customer_id":
                    payload.get("customerId", "") or "",
                "queued": bool(payload.get("customerId")),
            },
        )

    # ── Opt-out ────────────────────────────────────────────────────

    def _data_sale_opt_out(self, params: dict[str, Any]) -> Any:
        email = params.get("email")
        if not isinstance(email, str) or not email.strip():
            raise AdapterValidationError(
                self.name,
                "'email' is required (the address requesting the "
                "do-not-sell flag — CCPA accepts unregistered emails "
                "too, so this is NOT the customer GID)",
            )
        email_norm = email.strip()
        if not _EMAIL_REGEX.match(email_norm):
            raise AdapterValidationError(
                self.name,
                f"'email' is not a syntactically valid address: "
                f"{email_norm!r}",
            )

        data = self._gql(_DATA_SALE_OPT_OUT_MUTATION, {
            "email": email_norm,
        })
        self._check_user_errors(data, "dataSaleOptOut")
        payload = data.get("dataSaleOptOut") or {}
        return self._success(
            Capability.SHOPIFY_DATA_SALE_OPT_OUT,
            data={
                "customer_id":
                    payload.get("customerId", "") or "",
                "email": email_norm,
                "matched_existing_customer":
                    bool(payload.get("customerId")),
            },
        )
