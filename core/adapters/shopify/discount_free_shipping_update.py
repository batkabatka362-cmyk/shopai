"""ShopifyDiscountFreeShippingUpdateAdapter — update existing free-ship.

The existing ``discount_code_free_shipping.py`` adapter creates new
free-shipping CODE discounts; ``discount_automatic_bxgy.py`` and
``discount_automatic.py`` create automatic discounts but the
free-shipping AUTOMATIC create lives elsewhere (covered by
``discount_automatic.py``'s freeShipping branch). The UPDATE side for
both flavours was uncovered:

  * **discountAutomaticFreeShippingUpdate** — extend the run window,
    add a country to the eligible-destination list, raise the
    minimum-subtotal threshold, change the cap on shipping cost
    waived (``maximumShippingPrice``), or flip
    appliesOnSubscription on/off.
  * **discountCodeFreeShippingUpdate** — same field set plus the
    code-discount-only knobs: ``code`` (rename), ``usageLimit``,
    ``appliesOncePerCustomer``.

ShopAI's pricing engine writes these whenever:
  * A merchant extends an active SHIPFREE promotion past its
    original end date.
  * The international engine adds a country to an existing eligible
    list as the merchant unlocks new markets.
  * A goodwill-recovery flow raises the per-order shipping cap on a
    one-off restored discount.

Capabilities:

  * ``SHOPIFY_UPDATE_DISCOUNT_AUTO_FREE_SHIPPING`` —
    discountAutomaticFreeShippingUpdate. Pattern A: id at field
    level + ``DiscountAutomaticFreeShippingInput`` body.
  * ``SHOPIFY_UPDATE_DISCOUNT_CODE_FREE_SHIPPING`` —
    discountCodeFreeShippingUpdate. Same shape; body type is
    ``DiscountCodeFreeShippingInput`` (superset — adds code,
    usageLimit, appliesOncePerCustomer).

Friendly call shape::

    {"id":               "gid://shopify/DiscountAutomaticNode/1",
     "title":            "Free shipping over $50 (extended)",
     "ends_at":          "2027-06-30T23:59:59Z",
     "minimum_subtotal": "50.00",
     "destination": {
       "add_countries":     ["MX"],
       "remove_countries":  ["DE"],
       "include_rest_of_world": False,
     },
     "maximum_shipping_price": "20.00",
     "combines_with": {
       "product_discounts": True,
       "order_discounts":   False,
     }}

DiscountCountriesInput supports partial diffs: ``add`` /
``remove`` lists. Adapter exposes those as
``destination.add_countries`` / ``remove_countries`` (no full-list
replacement — Shopify wants the diff).

Pattern A — id at GraphQL field level.
Pattern F — DiscountUserError HAS code (matches
discounts.py and friends).

Pattern E note: gated by ``write_discounts``.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_DISCOUNT_FIELDS = """
title
status
startsAt
endsAt
combinesWith {
  productDiscounts
  orderDiscounts
  shippingDiscounts
}
minimumRequirement {
  ... on DiscountMinimumSubtotal {
    greaterThanOrEqualToSubtotal {
      amount
      currencyCode
    }
  }
  ... on DiscountMinimumQuantity {
    greaterThanOrEqualToQuantity
  }
}
destinationSelection {
  ... on DiscountCountryAll { allCountries }
  ... on DiscountCountries {
    countries
    includeRestOfWorld
  }
}
maximumShippingPrice {
  amount
  currencyCode
}
""".strip()


_AUTOMATIC_UPDATE_MUTATION = f"""
mutation discountAutomaticFreeShippingUpdate(
  $id: ID!,
  $freeShippingAutomaticDiscount: DiscountAutomaticFreeShippingInput!
) {{
  discountAutomaticFreeShippingUpdate(
    id: $id,
    freeShippingAutomaticDiscount: $freeShippingAutomaticDiscount
  ) {{
    automaticDiscountNode {{
      id
      automaticDiscount {{
        ... on DiscountAutomaticFreeShipping {{
          {_DISCOUNT_FIELDS}
        }}
      }}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


_CODE_UPDATE_MUTATION = f"""
mutation discountCodeFreeShippingUpdate(
  $id: ID!,
  $freeShippingCodeDiscount: DiscountCodeFreeShippingInput!
) {{
  discountCodeFreeShippingUpdate(
    id: $id,
    freeShippingCodeDiscount: $freeShippingCodeDiscount
  ) {{
    codeDiscountNode {{
      id
      codeDiscount {{
        ... on DiscountCodeFreeShipping {{
          {_DISCOUNT_FIELDS}
          codes(first: 1) {{
            edges {{ node {{ code }} }}
          }}
          usageLimit
          appliesOncePerCustomer
        }}
      }}
    }}
    userErrors {{
      field
      message
      code
    }}
  }}
}}
""".strip()


class ShopifyDiscountFreeShippingUpdateAdapter(ShopifyBaseAdapter):
    name = "shopify_discount_free_shipping_update"
    capabilities = {
        Capability.SHOPIFY_UPDATE_DISCOUNT_AUTO_FREE_SHIPPING,
        Capability.SHOPIFY_UPDATE_DISCOUNT_CODE_FREE_SHIPPING,
    }
    required_scopes = frozenset({"write_discounts"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_UPDATE_DISCOUNT_AUTO_FREE_SHIPPING:
            return self._update_automatic(params)
        if capability == \
                Capability.SHOPIFY_UPDATE_DISCOUNT_CODE_FREE_SHIPPING:
            return self._update_code(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Update automatic ───────────────────────────────────────────

    def _update_automatic(self, params: dict[str, Any]) -> Any:
        discount_id = self._extract_id(params)
        body = self._build_input(params, allow_code_fields=False)
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one updatable field",
            )
        data = self._gql(_AUTOMATIC_UPDATE_MUTATION, {
            "id": discount_id,
            "freeShippingAutomaticDiscount": body,
        })
        self._check_user_errors(
            data, "discountAutomaticFreeShippingUpdate",
        )
        payload = data.get(
            "discountAutomaticFreeShippingUpdate",
        ) or {}
        node = payload.get("automaticDiscountNode") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_DISCOUNT_AUTO_FREE_SHIPPING,
            data={
                "discount_id": (
                    node.get("id", "")
                    if isinstance(node, dict) else ""
                ) or "",
                "discount": self._normalise(
                    (node.get("automaticDiscount") or {})
                    if isinstance(node, dict) else {},
                ),
            },
        )

    # ── Update code ────────────────────────────────────────────────

    def _update_code(self, params: dict[str, Any]) -> Any:
        discount_id = self._extract_id(params)
        body = self._build_input(params, allow_code_fields=True)
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one updatable field",
            )
        data = self._gql(_CODE_UPDATE_MUTATION, {
            "id": discount_id,
            "freeShippingCodeDiscount": body,
        })
        self._check_user_errors(
            data, "discountCodeFreeShippingUpdate",
        )
        payload = data.get("discountCodeFreeShippingUpdate") or {}
        node = payload.get("codeDiscountNode") or {}
        return self._success(
            Capability.SHOPIFY_UPDATE_DISCOUNT_CODE_FREE_SHIPPING,
            data={
                "discount_id": (
                    node.get("id", "")
                    if isinstance(node, dict) else ""
                ) or "",
                "discount": self._normalise(
                    (node.get("codeDiscount") or {})
                    if isinstance(node, dict) else {},
                    is_code=True,
                ),
            },
        )

    # ── Helpers ────────────────────────────────────────────────────

    def _extract_id(self, params: dict[str, Any]) -> str:
        discount_id = (
            params.get("id")
            or params.get("discount_id")
            or params.get("discountId")
        )
        if not isinstance(discount_id, str) or not discount_id.strip():
            raise AdapterValidationError(
                self.name,
                "'id' (Shopify GID for the discount node) is required",
            )
        return discount_id.strip()

    def _build_input(
        self,
        params: dict[str, Any],
        *,
        allow_code_fields: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}

        title = params.get("title")
        if isinstance(title, str) and title.strip():
            out["title"] = title.strip()

        starts_at = params.get("starts_at") or params.get("startsAt")
        if starts_at is not None:
            if not isinstance(starts_at, str) or not starts_at.strip():
                raise AdapterValidationError(
                    self.name, "'starts_at' must be an ISO datetime",
                )
            out["startsAt"] = starts_at.strip()

        ends_at = params.get("ends_at") or params.get("endsAt")
        if ends_at is not None:
            if not isinstance(ends_at, str):
                raise AdapterValidationError(
                    self.name, "'ends_at' must be a string or None",
                )
            out["endsAt"] = ends_at.strip() if ends_at.strip() else None

        if "minimum_subtotal" in params and \
                params["minimum_subtotal"] is not None:
            try:
                out["minimumRequirement"] = {
                    "subtotal": {
                        "greaterThanOrEqualToSubtotal":
                            float(params["minimum_subtotal"]),
                    },
                }
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'minimum_subtotal' must be numeric",
                ) from exc

        max_ship = (
            params.get("maximum_shipping_price")
            or params.get("maximumShippingPrice")
        )
        if max_ship is not None:
            try:
                out["maximumShippingPrice"] = float(max_ship)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'maximum_shipping_price' must be numeric",
                ) from exc

        for snake, camel in (
            ("applies_on_one_time_purchase", "appliesOnOneTimePurchase"),
            ("applies_on_subscription", "appliesOnSubscription"),
        ):
            if snake in params and params[snake] is not None:
                out[camel] = bool(params[snake])

        recurring = params.get("recurring_cycle_limit")
        if recurring is not None:
            try:
                out["recurringCycleLimit"] = int(recurring)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'recurring_cycle_limit' must be an integer",
                ) from exc

        combines = self._build_combines_with(params.get("combines_with"))
        if combines:
            out["combinesWith"] = combines

        destination = self._build_destination(params.get("destination"))
        if destination is not None:
            out["destination"] = destination

        if allow_code_fields:
            code = params.get("code")
            if isinstance(code, str) and code.strip():
                out["code"] = code.strip()
            usage_limit = (
                params.get("usage_limit") or params.get("usageLimit")
            )
            if usage_limit is not None:
                try:
                    out["usageLimit"] = int(usage_limit)
                except (TypeError, ValueError) as exc:
                    raise AdapterValidationError(
                        self.name,
                        "'usage_limit' must be an integer",
                    ) from exc
            applies_once = (
                params.get("applies_once_per_customer")
                if "applies_once_per_customer" in params
                else params.get("appliesOncePerCustomer")
            )
            if applies_once is not None:
                out["appliesOncePerCustomer"] = bool(applies_once)

        return out

    def _build_combines_with(self, raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'combines_with' must be a dict {product_discounts?, "
                "order_discounts?, shipping_discounts?}",
            )
        out: dict[str, Any] = {}
        for snake, camel in (
            ("product_discounts", "productDiscounts"),
            ("order_discounts", "orderDiscounts"),
            ("shipping_discounts", "shippingDiscounts"),
        ):
            v = raw.get(snake)
            if v is None and camel in raw:
                v = raw[camel]
            if v is not None:
                out[camel] = bool(v)
        return out or None

    def _build_destination(self, raw: Any) -> dict[str, Any] | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'destination' must be a dict — supply 'all' OR "
                "'add_countries'/'remove_countries' for partial diff",
            )
        if raw.get("all"):
            return {"all": True}
        countries: dict[str, Any] = {}
        add = raw.get("add_countries") or raw.get("countries")
        if add is not None:
            if not isinstance(add, list) or not all(
                isinstance(c, str) for c in add
            ):
                raise AdapterValidationError(
                    self.name,
                    "'destination.add_countries' must be a list of "
                    "ISO 3166-1 alpha-2 codes",
                )
            countries["add"] = [
                c.strip().upper() for c in add if c.strip()
            ]
        remove = raw.get("remove_countries")
        if remove is not None:
            if not isinstance(remove, list) or not all(
                isinstance(c, str) for c in remove
            ):
                raise AdapterValidationError(
                    self.name,
                    "'destination.remove_countries' must be a list of "
                    "ISO 3166-1 alpha-2 codes",
                )
            countries["remove"] = [
                c.strip().upper() for c in remove if c.strip()
            ]
        if "include_rest_of_world" in raw:
            countries["includeRestOfWorld"] = bool(
                raw["include_rest_of_world"],
            )
        if not countries:
            raise AdapterValidationError(
                self.name,
                "'destination' must include 'all', "
                "'add_countries', 'remove_countries', or "
                "'include_rest_of_world'",
            )
        return {"countries": countries}

    @staticmethod
    def _normalise(
        node: dict[str, Any],
        *,
        is_code: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        combines = node.get("combinesWith") or {}
        min_req = node.get("minimumRequirement") or {}
        dest = node.get("destinationSelection") or {}
        max_ship = node.get("maximumShippingPrice") or {}
        try:
            max_amount = (
                float(max_ship.get("amount", 0) or 0)
                if isinstance(max_ship, dict) else 0.0
            )
        except (TypeError, ValueError):
            max_amount = 0.0
        out = {
            "title": node.get("title", "") or "",
            "status": node.get("status", "") or "",
            "starts_at": node.get("startsAt", "") or "",
            "ends_at": node.get("endsAt", "") or "",
            "combines_with_product": bool(
                combines.get("productDiscounts", False)
                if isinstance(combines, dict) else False
            ),
            "combines_with_order": bool(
                combines.get("orderDiscounts", False)
                if isinstance(combines, dict) else False
            ),
            "combines_with_shipping": bool(
                combines.get("shippingDiscounts", False)
                if isinstance(combines, dict) else False
            ),
            "minimum_requirement_kind": (
                "subtotal" if isinstance(min_req, dict) and
                "greaterThanOrEqualToSubtotal" in min_req
                else "quantity" if isinstance(min_req, dict) and
                "greaterThanOrEqualToQuantity" in min_req
                else ""
            ),
            "destination_all_countries": bool(
                dest.get("allCountries", False)
                if isinstance(dest, dict) else False
            ),
            "destination_countries": (
                dest.get("countries", []) or []
                if isinstance(dest, dict) else []
            ),
            "destination_include_rest_of_world": bool(
                dest.get("includeRestOfWorld", False)
                if isinstance(dest, dict) else False
            ),
            "maximum_shipping_amount": max_amount,
            "maximum_shipping_currency": (
                max_ship.get("currencyCode", "")
                if isinstance(max_ship, dict) else ""
            ) or "",
        }
        if is_code:
            out["usage_limit"] = int(node.get("usageLimit", 0) or 0)
            out["applies_once_per_customer"] = bool(
                node.get("appliesOncePerCustomer", False),
            )
            codes_raw = node.get("codes") or {}
            edges = (
                codes_raw.get("edges") or []
                if isinstance(codes_raw, dict) else []
            )
            first_code = ""
            if edges and isinstance(edges[0], dict):
                first_code = (
                    (edges[0].get("node") or {}).get("code", "")
                    or ""
                )
            out["code"] = first_code
        return out
