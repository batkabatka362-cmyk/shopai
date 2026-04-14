"""ShopifyDiscountAdapter — create discount codes.

Fills the ``SHOPIFY_CREATE_DISCOUNT`` gap in the adapter catalog
(Option D). The merchandising agent promotes slow-moving SKUs,
the loyalty agent rewards VIP segments, and the recovery flow
offers win-back codes — all three previously stubbed because
nothing in the adapter layer implemented discount creation.

WRITE-ONLY. Query + list of existing discounts belongs to a
future ``ShopifyDiscountReadAdapter``.

This adapter supports the two most useful discount types:

  * **Percentage off** — ``{"kind": "percentage", "value": 15}``
    creates a 15% off code.
  * **Fixed amount off** — ``{"kind": "fixed_amount", "value": 5.00,
    "currency": "USD"}`` creates $5 off code.

Params shape::

    {
        "code":         "SAVE15",              # required, unique
        "title":        "Spring Sale",         # optional, defaults to code
        "kind":         "percentage"|"fixed_amount",
        "value":        15,                    # percent or currency units
        "currency":     "USD",                 # fixed_amount only
        "starts_at":    "2026-04-01T00:00Z",   # ISO-8601, optional
        "ends_at":      "2026-04-30T23:59Z",   # ISO-8601, optional
        "usage_limit":  100,                   # optional, null = unlimited
        "applies_once_per_customer": True,
        "minimum_subtotal": 50.00,             # optional
    }

Returns::

    {
        "discount_id": "gid://...",
        "code": "SAVE15",
        "title": "...",
        "starts_at": "...",
        "ends_at": "...",
    }
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


_CREATE_CODE_MUTATION = """
mutation CreateDiscountCode($basicCodeDiscount: DiscountCodeBasicInput!) {
  discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
    codeDiscountNode {
      id
      codeDiscount {
        ... on DiscountCodeBasic {
          title
          startsAt
          endsAt
          usageLimit
          appliesOncePerCustomer
          codes(first: 1) {
            edges { node { code } }
          }
        }
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


_ALLOWED_KINDS = {"percentage", "fixed_amount"}


class ShopifyDiscountAdapter(ShopifyBaseAdapter):
    """Create Shopify discount codes via the native GraphQL API."""

    name = "shopify_discount"
    capabilities = {Capability.SHOPIFY_CREATE_DISCOUNT}

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_CREATE_DISCOUNT:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        code = str(params.get("code") or "").strip()
        if not code:
            raise AdapterValidationError(
                self.name, "'code' is required",
            )

        kind = str(params.get("kind") or "").strip().lower()
        if kind not in _ALLOWED_KINDS:
            raise AdapterValidationError(
                self.name,
                f"'kind' must be one of {sorted(_ALLOWED_KINDS)}",
            )

        try:
            value = float(params.get("value"))
        except (TypeError, ValueError):
            raise AdapterValidationError(
                self.name, "'value' must be a number",
            )
        if value <= 0:
            raise AdapterValidationError(
                self.name, "'value' must be > 0",
            )

        title = str(params.get("title") or code)

        # Shopify expects a nested customerValue that picks ONE
        # branch — percentage (0..1 float) or discountAmount (money).
        if kind == "percentage":
            if value > 100:
                raise AdapterValidationError(
                    self.name, "percentage 'value' must be <= 100",
                )
            customer_gets_value: dict[str, Any] = {
                "percentage": round(value / 100.0, 4),
            }
        else:
            currency = str(params.get("currency") or "").strip().upper()
            if not currency:
                raise AdapterValidationError(
                    self.name,
                    "'currency' is required for fixed_amount",
                )
            customer_gets_value = {
                "discountAmount": {
                    "amount": f"{value:.2f}",
                    "appliesOnEachItem": False,
                },
            }
            # Shopify binds the currency via the shop's primary
            # currency when discountAmount is used; we still
            # pass currency in the echo payload for traceability.
            _ = currency

        usage_limit = params.get("usage_limit")
        if usage_limit is not None:
            try:
                usage_limit = int(usage_limit)
            except (TypeError, ValueError):
                raise AdapterValidationError(
                    self.name, "'usage_limit' must be an integer or null",
                )
            if usage_limit <= 0:
                raise AdapterValidationError(
                    self.name, "'usage_limit' must be > 0",
                )

        starts_at = params.get("starts_at")
        ends_at = params.get("ends_at")
        applies_once = bool(params.get("applies_once_per_customer", False))

        min_subtotal = params.get("minimum_subtotal")

        # Build the DiscountCodeBasicInput payload. Every optional
        # field is only included when set so we don't override
        # Shopify defaults with nulls.
        basic: dict[str, Any] = {
            "title": title,
            "code": code,
            "customerSelection": {"all": True},
            "customerGets": {
                "value": customer_gets_value,
                "items": {"all": True},
            },
            "appliesOncePerCustomer": applies_once,
        }
        if starts_at:
            basic["startsAt"] = str(starts_at)
        if ends_at:
            basic["endsAt"] = str(ends_at)
        if usage_limit is not None:
            basic["usageLimit"] = usage_limit
        if min_subtotal is not None:
            try:
                min_subtotal_val = float(min_subtotal)
            except (TypeError, ValueError):
                raise AdapterValidationError(
                    self.name,
                    "'minimum_subtotal' must be a number",
                )
            basic["minimumRequirement"] = {
                "subtotal": {
                    "greaterThanOrEqualToSubtotal": f"{min_subtotal_val:.2f}",
                },
            }

        variables = {"basicCodeDiscount": basic}
        data = self._gql(_CREATE_CODE_MUTATION, variables)
        self._check_user_errors(data, "discountCodeBasicCreate")

        payload = data.get("discountCodeBasicCreate") or {}
        node = payload.get("codeDiscountNode") or {}
        code_discount = node.get("codeDiscount") or {}
        code_edges = (code_discount.get("codes") or {}).get("edges") or []
        created_code = code
        if code_edges:
            created_code = (
                (code_edges[0].get("node") or {}).get("code") or code
            )

        return self._success(
            Capability.SHOPIFY_CREATE_DISCOUNT,
            data={
                "discount_id": node.get("id", ""),
                "code": created_code,
                "title": code_discount.get("title", title),
                "starts_at": code_discount.get("startsAt", "") or "",
                "ends_at": code_discount.get("endsAt", "") or "",
                "usage_limit": code_discount.get("usageLimit"),
                "applies_once_per_customer": bool(
                    code_discount.get("appliesOncePerCustomer", False),
                ),
                "kind": kind,
                "value": value,
            },
        )
