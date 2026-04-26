"""ShopifyDiscountCodeFreeShippingAdapter — free-shipping code discounts.

Companion to ``discounts.py`` (BASIC code-based percentage/amount),
``discount_code_bxgy.py`` (buy-x-get-y codes), and
``discount_automatic.py`` (automatic site-wide). This adapter is
the FOURTH leg: FREE SHIPPING code discounts ("Use code SHIPFREE
for free shipping over $50").

ShopAI's pricing + marketing engines use these for:

  * Cart-recovery email coupons that waive shipping ("Forgot your
    cart? Use SHIPFREE.").
  * Threshold-based promotions ("Free shipping at $50+").
  * Country-specific shipping incentives ("FREESHIPUSA — domestic
    shipping waived for orders > $25").

Capabilities:

  * ``SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING`` — create a free-
    shipping code with optional minimum-subtotal threshold and
    country whitelist.
  * ``SHOPIFY_DELETE_DISCOUNT_FREE_SHIPPING`` — reuses
    discountCodeDelete from discounts.py (delete is type-agnostic).

Friendly create call shape::

    {"title":          "Free Shipping over $50",
     "code":           "SHIPFREE50",
     "starts_at":      "2026-04-26T00:00:00Z",
     "ends_at":        "2026-12-31T23:59:59Z",
     "minimum_subtotal": "50.00",
     "destination": {                         # optional
        "all": True                           # or
        "countries": ["US", "CA"],            # or
     },
     "appliesOnce_per_customer": True,
     "usage_limit": 1000}

Pattern A: variable name ``freeShippingCodeDiscount`` matches the
input type. Same convention as discounts.py / validations.py.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CREATE_FREE_SHIPPING_MUTATION = """
mutation discountCodeFreeShippingCreate(
  $freeShippingCodeDiscount: DiscountCodeFreeShippingInput!
) {
  discountCodeFreeShippingCreate(
    freeShippingCodeDiscount: $freeShippingCodeDiscount
  ) {
    codeDiscountNode {
      id
      codeDiscount {
        ... on DiscountCodeFreeShipping {
          title
          summary
          status
          startsAt
          endsAt
          appliesOncePerCustomer
          usageLimit
          minimumRequirement {
            __typename
            ... on DiscountMinimumSubtotal {
              greaterThanOrEqualToSubtotal {
                amount
                currencyCode
              }
            }
          }
          destinationSelection {
            __typename
            ... on DiscountCountryAll {
              allCountries
            }
            ... on DiscountCountries {
              countries
              includeRestOfWorld
            }
          }
          codes(first: 5) {
            edges {
              node {
                code
              }
            }
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


_DELETE_DISCOUNT_MUTATION = """
mutation discountCodeDelete($id: ID!) {
  discountCodeDelete(id: $id) {
    deletedCodeDiscountId
    userErrors {
      field
      message
      code
    }
  }
}
""".strip()


class ShopifyDiscountCodeFreeShippingAdapter(ShopifyBaseAdapter):
    name = "shopify_discount_code_free_shipping"
    capabilities = {
        Capability.SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING,
        Capability.SHOPIFY_DELETE_DISCOUNT_FREE_SHIPPING,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_DISCOUNT_FREE_SHIPPING:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        discount_input = self._build_input(params)
        data = self._gql(_CREATE_FREE_SHIPPING_MUTATION, {
            "freeShippingCodeDiscount": discount_input,
        })
        self._check_user_errors(data, "discountCodeFreeShippingCreate")
        payload = data.get("discountCodeFreeShippingCreate") or {}
        node = payload.get("codeDiscountNode") or {}
        discount = node.get("codeDiscount") or {}
        codes_raw = (discount.get("codes") or {}).get("edges") or []
        codes = [
            (e.get("node") or {}).get("code", "") or ""
            for e in codes_raw if isinstance(e, dict)
        ]
        return self._success(
            Capability.SHOPIFY_CREATE_DISCOUNT_FREE_SHIPPING,
            data={
                "id": node.get("id", "") or "",
                "title": discount.get("title", "") or "",
                "status": discount.get("status", "") or "",
                "starts_at": discount.get("startsAt", "") or "",
                "ends_at": discount.get("endsAt", "") or "",
                "applies_once_per_customer": bool(
                    discount.get("appliesOncePerCustomer", False),
                ),
                "usage_limit": int(discount.get("usageLimit") or 0) or 0,
                "codes": codes,
            },
        )

    # ── Delete ─────────────────────────────────────────────────────

    def _delete(self, params: dict[str, Any]) -> Any:
        discount_id = params.get("id") or params.get("discount_id")
        if not isinstance(discount_id, str) or not discount_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the code discount node) is required",
            )
        data = self._gql(_DELETE_DISCOUNT_MUTATION, {
            "id": discount_id.strip(),
        })
        self._check_user_errors(data, "discountCodeDelete")
        payload = data.get("discountCodeDelete") or {}
        return self._success(
            Capability.SHOPIFY_DELETE_DISCOUNT_FREE_SHIPPING,
            data={
                "deleted_id": (
                    payload.get("deletedCodeDiscountId", "") or ""
                ),
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    def _build_input(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name, "'title' is required",
            )

        code = params.get("code")
        if not isinstance(code, str) or not code.strip():
            raise AdapterValidationError(
                self.name, "'code' is required",
            )

        starts_at = params.get("starts_at") or params.get("startsAt")
        if not isinstance(starts_at, str) or not starts_at.strip():
            raise AdapterValidationError(
                self.name, "'starts_at' is required (ISO-8601)",
            )

        out: dict[str, Any] = {
            "title": title.strip(),
            "code": code.strip(),
            "startsAt": starts_at.strip(),
        }

        ends_at = params.get("ends_at") or params.get("endsAt")
        if ends_at is not None:
            if not isinstance(ends_at, str):
                raise AdapterValidationError(
                    self.name, "'ends_at' must be a string",
                )
            out["endsAt"] = ends_at.strip()

        applies_once = params.get("applies_once_per_customer")
        if applies_once is None:
            applies_once = params.get("appliesOncePerCustomer")
        if applies_once is not None:
            out["appliesOncePerCustomer"] = bool(applies_once)

        usage_limit = params.get("usage_limit") or params.get("usageLimit")
        if usage_limit is not None:
            try:
                out["usageLimit"] = int(usage_limit)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'usage_limit' must be an integer",
                ) from exc

        # Minimum subtotal threshold (optional).
        minimum_subtotal = params.get("minimum_subtotal")
        if minimum_subtotal is not None:
            try:
                subtotal_float = float(minimum_subtotal)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name, "'minimum_subtotal' must be numeric",
                ) from exc
            out["minimumRequirement"] = {
                "subtotal": {
                    "greaterThanOrEqualToSubtotal": subtotal_float,
                },
            }

        # Destination scoping (default: all countries).
        destination = params.get("destination")
        if destination is None:
            out["destination"] = {"all": True}
        else:
            out["destination"] = self._build_destination(destination)

        # customerSelection — silently REQUIRED on every code discount
        # (Pattern C from BXGY adapter). Default to all customers.
        customer_selection = params.get("customer_selection") or params.get(
            "customerSelection"
        )
        if customer_selection is None:
            out["customerSelection"] = {"all": True}
        else:
            if not isinstance(customer_selection, dict):
                raise AdapterValidationError(
                    self.name,
                    "'customer_selection' must be a dict",
                )
            if customer_selection.get("all"):
                out["customerSelection"] = {"all": True}
            else:
                customer_ids = customer_selection.get("customers") or []
                if not isinstance(customer_ids, list) or not all(
                    isinstance(c, str) for c in customer_ids
                ):
                    raise AdapterValidationError(
                        self.name,
                        "'customer_selection.customers' must be a list "
                        "of GIDs",
                    )
                out["customerSelection"] = {
                    "customers": {"add": [
                        c.strip() for c in customer_ids if c.strip()
                    ]},
                }

        return out

    def _build_destination(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'destination' must be a dict — one of "
                "{'all': True} / {'countries': [...]}",
            )
        if raw.get("all"):
            return {"all": True}
        countries = raw.get("countries")
        if countries is not None:
            if not isinstance(countries, list) or not all(
                isinstance(c, str) for c in countries
            ):
                raise AdapterValidationError(
                    self.name,
                    "'destination.countries' must be a list of "
                    "2-letter ISO country codes",
                )
            include_row = bool(raw.get("include_rest_of_world", False))
            return {"countries": {
                "add": [c.strip().upper() for c in countries if c.strip()],
                "includeRestOfWorld": include_row,
            }}
        raise AdapterValidationError(
            self.name,
            "'destination' must specify 'all' or 'countries'",
        )
