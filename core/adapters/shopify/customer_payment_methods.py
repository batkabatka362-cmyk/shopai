"""ShopifyCustomerPaymentMethodsAdapter — vaulted payment methods.

A customer payment method is a tokenized payment instrument Shopify
stores on behalf of the merchant — credit card, PayPal account,
shop pay, etc. — for re-billing without prompting the customer.
ShopAI's subscription engine + B2B engine read these to:

  * Verify a customer has a vaulted method before scheduling a
    recurring charge (else the next contract billing fails).
  * Revoke an expired or compromised method (e.g. after a chargeback).
  * Surface "payment method failing" diagnostics in the operator
    dashboard.

Capabilities (read + revoke; create requires PCI-compliant
tokenization that's outside autonomous-AI scope):

  * ``SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS``  — per-customer list.
  * ``SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD``    — single method by GID.
  * ``SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD`` — invalidate a method.

Pattern A note: customerPaymentMethods is queried under a customer
node — the GraphQL API doesn't expose a top-level
Query.customerPaymentMethods connection. The adapter takes a
customer_id and reaches in via ``customer(id:).paymentMethods``.

Pattern E note: gated by ``read_customer_payment_methods`` scope.
The revoke mutation needs ``write_customer_payment_methods``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_PAYMENT_METHOD_FIELDS = """
id
revokedAt
revokedReason
instrument {
  __typename
  ... on CustomerCreditCard {
    brand
    expiresSoon
    expiryMonth
    expiryYear
    firstDigits
    lastDigits
    maskedNumber
    name
    source
    virtualLastDigits
  }
  ... on CustomerPaypalBillingAgreement {
    paypalAccountEmail
    inactive
  }
  ... on CustomerShopPayAgreement {
    expiresSoon
    expiryMonth
    expiryYear
    inactive
    lastDigits
    maskedNumber
  }
}
""".strip()


_LIST_PAYMENT_METHODS_QUERY = f"""
query customerPaymentMethods(
  $id: ID!,
  $first: Int!,
  $after: String
) {{
  customer(id: $id) {{
    id
    paymentMethods(first: $first, after: $after) {{
      pageInfo {{
        hasNextPage
        endCursor
      }}
      edges {{
        node {{
          {_PAYMENT_METHOD_FIELDS}
        }}
      }}
    }}
  }}
}}
""".strip()


_GET_PAYMENT_METHOD_QUERY = f"""
query customerPaymentMethod($id: ID!) {{
  customerPaymentMethod(id: $id) {{
    {_PAYMENT_METHOD_FIELDS}
  }}
}}
""".strip()


_REVOKE_PAYMENT_METHOD_MUTATION = """
mutation customerPaymentMethodRevoke($customerPaymentMethodId: ID!) {
  customerPaymentMethodRevoke(
    customerPaymentMethodId: $customerPaymentMethodId
  ) {
    revokedCustomerPaymentMethodId
    userErrors {
      field
      message
    }
  }
}
""".strip()


_DEFAULT_LIST_LIMIT = 50
_MAX_LIST_LIMIT = 250


class ShopifyCustomerPaymentMethodsAdapter(ShopifyBaseAdapter):
    name = "shopify_customer_payment_methods"
    capabilities = {
        Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS,
        Capability.SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD,
        Capability.SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD,
    }
    # Shopify removed ``write_customer_payment_methods`` in 2026+
    # (only read remains in the Partners Dashboard scope selector).
    # Revoke + other write-side operations on payment methods are
    # now subsumed by the broader ``write_customers`` scope, since
    # they fundamentally modify customer-attached data.
    required_scopes = frozenset({
        "read_customer_payment_methods",
        "write_customers",
    })

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS:
            return self._list(params)
        if capability == Capability.SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD:
            return self._get(params)
        if capability == Capability.SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD:
            return self._revoke(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── List ───────────────────────────────────────────────────────

    def _list(self, params: dict[str, Any]) -> Any:
        customer_id = params.get("customer_id") or params.get("customerId")
        if not isinstance(customer_id, str) or not customer_id.strip():
            raise AdapterValidationError(
                self.name,
                "'customer_id' (Shopify GID) is required — the API "
                "doesn't expose a top-level paymentMethods connection",
            )

        limit = params.get("limit", _DEFAULT_LIST_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIST_LIMIT
        limit = max(1, min(limit, _MAX_LIST_LIMIT))

        cursor = params.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise AdapterValidationError(
                self.name, "'cursor' must be a string or None",
            )

        data = self._gql(_LIST_PAYMENT_METHODS_QUERY, {
            "id": customer_id.strip(),
            "first": limit,
            "after": cursor,
        })
        customer = data.get("customer") or {}
        envelope = customer.get("paymentMethods") or {}
        page_info = envelope.get("pageInfo") or {}
        edges = envelope.get("edges") or []
        methods = [
            self._normalise_method(edge.get("node") or {})
            for edge in edges if isinstance(edge, dict)
        ]
        return self._success(
            Capability.SHOPIFY_LIST_CUSTOMER_PAYMENT_METHODS,
            data={
                "customer_id": customer.get("id", "") or "",
                "payment_methods": methods,
                "count": len(methods),
                "has_next_page": bool(page_info.get("hasNextPage", False)),
                "end_cursor": page_info.get("endCursor", "") or "",
                "customer_found": bool(customer),
            },
        )

    # ── Get ────────────────────────────────────────────────────────

    def _get(self, params: dict[str, Any]) -> Any:
        method_id = params.get("id") or params.get("payment_method_id")
        if not isinstance(method_id, str) or not method_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the payment method) is required",
            )
        data = self._gql(_GET_PAYMENT_METHOD_QUERY, {"id": method_id.strip()})
        node = data.get("customerPaymentMethod") or {}
        return self._success(
            Capability.SHOPIFY_GET_CUSTOMER_PAYMENT_METHOD,
            data={
                "payment_method": self._normalise_method(node),
                "found": bool(node),
            },
        )

    # ── Revoke ─────────────────────────────────────────────────────

    def _revoke(self, params: dict[str, Any]) -> Any:
        method_id = params.get("id") or params.get("payment_method_id")
        if not isinstance(method_id, str) or not method_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the payment method) is required",
            )
        data = self._gql(_REVOKE_PAYMENT_METHOD_MUTATION, {
            "customerPaymentMethodId": method_id.strip(),
        })
        self._check_user_errors(data, "customerPaymentMethodRevoke")
        payload = data.get("customerPaymentMethodRevoke") or {}
        return self._success(
            Capability.SHOPIFY_REVOKE_CUSTOMER_PAYMENT_METHOD,
            data={
                "revoked_id": (
                    payload.get("revokedCustomerPaymentMethodId", "") or ""
                ),
            },
        )

    # ── Normalisation ──────────────────────────────────────────────

    @staticmethod
    def _normalise_method(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        instrument = node.get("instrument") or {}
        kind = (
            instrument.get("__typename", "")
            if isinstance(instrument, dict) else ""
        ) or ""
        out: dict[str, Any] = {
            "id": node.get("id", "") or "",
            "revoked_at": node.get("revokedAt", "") or "",
            "revoked_reason": node.get("revokedReason", "") or "",
            "instrument_kind": kind,
            "is_active": not bool(node.get("revokedAt")),
        }
        if not isinstance(instrument, dict) or not instrument:
            return out

        if kind == "CustomerCreditCard":
            out.update({
                "brand": instrument.get("brand", "") or "",
                "expires_soon": bool(instrument.get("expiresSoon", False)),
                "expiry_month": int(instrument.get("expiryMonth") or 0),
                "expiry_year": int(instrument.get("expiryYear") or 0),
                "first_digits": instrument.get("firstDigits", "") or "",
                "last_digits": instrument.get("lastDigits", "") or "",
                "masked_number": instrument.get("maskedNumber", "") or "",
                "card_holder_name": instrument.get("name", "") or "",
                "source": instrument.get("source", "") or "",
                "virtual_last_digits": (
                    instrument.get("virtualLastDigits", "") or ""
                ),
            })
        elif kind == "CustomerPaypalBillingAgreement":
            out.update({
                "paypal_account_email": (
                    instrument.get("paypalAccountEmail", "") or ""
                ),
                "inactive": bool(instrument.get("inactive", False)),
            })
        elif kind == "CustomerShopPayAgreement":
            out.update({
                "expires_soon": bool(instrument.get("expiresSoon", False)),
                "expiry_month": int(instrument.get("expiryMonth") or 0),
                "expiry_year": int(instrument.get("expiryYear") or 0),
                "inactive": bool(instrument.get("inactive", False)),
                "last_digits": instrument.get("lastDigits", "") or "",
                "masked_number": instrument.get("maskedNumber", "") or "",
            })
        return out
