"""ShopifyDiscountAutomaticBxgyAdapter — automatic BXGY + free shipping.

Companion to ``discount_automatic.py`` (BASIC automatic — site-wide
percentage / amount with no code). This adapter ships the two
remaining automatic-discount mutations:

  * ``discountAutomaticBxgyCreate``         — automatic buy-x-get-y
    ("Cart contains 2 from Camping → free Lantern" — no code).
  * ``discountAutomaticFreeShippingCreate`` — automatic free
    shipping ("Cart over \$75 → shipping waived, no code").

Use cases:

  * Auto-apply BOGO bundles when the cart matches a rule (no
    code-typing required from the customer).
  * Site-wide free-shipping above a threshold ("Free shipping over
    \$75!") that engines can flip on/off based on margin signals.

Capabilities:

  * ``SHOPIFY_CREATE_AUTOMATIC_BXGY``          — automatic BXGY.
  * ``SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING`` — automatic free
    shipping.

Delete reuses ``discount_automatic.py``'s
``SHOPIFY_DELETE_AUTOMATIC_DISCOUNT`` capability — the
``discountAutomaticDelete`` mutation is type-agnostic.

Pattern A: variable names ``automaticBxgyDiscount`` and
``freeShippingAutomaticDiscount`` match their input types.

Pattern C honoured: same scoping rules as
``discount_code_bxgy.py`` — items must be products / collections,
not ``all`` (Shopify's BXGY engine needs scoped sides).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CREATE_AUTOMATIC_BXGY_MUTATION = """
mutation discountAutomaticBxgyCreate(
  $automaticBxgyDiscount: DiscountAutomaticBxgyInput!
) {
  discountAutomaticBxgyCreate(
    automaticBxgyDiscount: $automaticBxgyDiscount
  ) {
    automaticDiscountNode {
      id
      automaticDiscount {
        ... on DiscountAutomaticBxgy {
          title
          summary
          status
          startsAt
          endsAt
          usesPerOrderLimit
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


_CREATE_AUTOMATIC_FREE_SHIPPING_MUTATION = """
mutation discountAutomaticFreeShippingCreate(
  $freeShippingAutomaticDiscount: DiscountAutomaticFreeShippingInput!
) {
  discountAutomaticFreeShippingCreate(
    freeShippingAutomaticDiscount: $freeShippingAutomaticDiscount
  ) {
    automaticDiscountNode {
      id
      automaticDiscount {
        ... on DiscountAutomaticFreeShipping {
          title
          summary
          status
          startsAt
          endsAt
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


class ShopifyDiscountAutomaticBxgyAdapter(ShopifyBaseAdapter):
    name = "shopify_discount_automatic_bxgy"
    capabilities = {
        Capability.SHOPIFY_CREATE_AUTOMATIC_BXGY,
        Capability.SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_AUTOMATIC_BXGY:
            return self._create_bxgy(params)
        if capability == Capability.SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING:
            return self._create_free_shipping(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create automatic BXGY ──────────────────────────────────────

    def _create_bxgy(self, params: dict[str, Any]) -> Any:
        discount_input = self._build_bxgy_input(params)
        data = self._gql(_CREATE_AUTOMATIC_BXGY_MUTATION, {
            "automaticBxgyDiscount": discount_input,
        })
        self._check_user_errors(data, "discountAutomaticBxgyCreate")
        payload = data.get("discountAutomaticBxgyCreate") or {}
        node = payload.get("automaticDiscountNode") or {}
        discount = node.get("automaticDiscount") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_AUTOMATIC_BXGY,
            data={
                "id": node.get("id", "") or "",
                "title": discount.get("title", "") or "",
                "status": discount.get("status", "") or "",
                "starts_at": discount.get("startsAt", "") or "",
                "ends_at": discount.get("endsAt", "") or "",
                "uses_per_order_limit": int(
                    discount.get("usesPerOrderLimit") or 0,
                ) or 0,
            },
        )

    # ── Create automatic free shipping ────────────────────────────

    def _create_free_shipping(self, params: dict[str, Any]) -> Any:
        discount_input = self._build_free_shipping_input(params)
        data = self._gql(_CREATE_AUTOMATIC_FREE_SHIPPING_MUTATION, {
            "freeShippingAutomaticDiscount": discount_input,
        })
        self._check_user_errors(data, "discountAutomaticFreeShippingCreate")
        payload = data.get("discountAutomaticFreeShippingCreate") or {}
        node = payload.get("automaticDiscountNode") or {}
        discount = node.get("automaticDiscount") or {}
        return self._success(
            Capability.SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING,
            data={
                "id": node.get("id", "") or "",
                "title": discount.get("title", "") or "",
                "status": discount.get("status", "") or "",
                "starts_at": discount.get("startsAt", "") or "",
                "ends_at": discount.get("endsAt", "") or "",
            },
        )

    # ── Input builders ────────────────────────────────────────────

    def _build_bxgy_input(self, params: dict[str, Any]) -> dict[str, Any]:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name, "'title' is required",
            )

        starts_at = params.get("starts_at") or params.get("startsAt")
        if not isinstance(starts_at, str) or not starts_at.strip():
            raise AdapterValidationError(
                self.name, "'starts_at' is required (ISO-8601)",
            )

        out: dict[str, Any] = {
            "title": title.strip(),
            "startsAt": starts_at.strip(),
        }

        ends_at = params.get("ends_at") or params.get("endsAt")
        if ends_at is not None:
            if not isinstance(ends_at, str):
                raise AdapterValidationError(
                    self.name, "'ends_at' must be a string",
                )
            out["endsAt"] = ends_at.strip()

        uses_per_order = params.get("uses_per_order_limit")
        if uses_per_order is None:
            uses_per_order = params.get("usesPerOrderLimit")
        if uses_per_order is not None:
            try:
                out["usesPerOrderLimit"] = int(uses_per_order)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'uses_per_order_limit' must be an integer",
                ) from exc

        out["customerBuys"] = self._build_customer_buys(
            params.get("customer_buys") or params.get("customerBuys"),
        )
        out["customerGets"] = self._build_customer_gets(
            params.get("customer_gets") or params.get("customerGets"),
        )

        return out

    def _build_customer_buys(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'customer_buys' is required (X side: items + quantity)",
            )
        value = raw.get("value")
        if not isinstance(value, dict) or "quantity" not in value:
            raise AdapterValidationError(
                self.name,
                "'customer_buys.value' must be a dict with 'quantity'",
            )
        try:
            qty = int(value["quantity"])
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                "'customer_buys.value.quantity' must be an integer",
            ) from exc
        if qty < 1:
            raise AdapterValidationError(
                self.name,
                "'customer_buys.value.quantity' must be >= 1",
            )
        items = self._build_items(
            raw.get("items"), label="customer_buys.items",
        )
        return {"value": {"quantity": str(qty)}, "items": items}

    def _build_customer_gets(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'customer_gets' is required (Y side: items + value)",
            )
        value = raw.get("value")
        if not isinstance(value, dict):
            raise AdapterValidationError(
                self.name,
                "'customer_gets.value' must be a dict",
            )

        get_quantity = raw.get("quantity") or value.get("quantity") or 1
        try:
            get_qty = int(get_quantity)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name,
                "'customer_gets.quantity' must be an integer",
            ) from exc
        if get_qty < 1:
            raise AdapterValidationError(
                self.name,
                "'customer_gets.quantity' must be >= 1",
            )

        if "percentage" in value:
            try:
                pct = float(value["percentage"])
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'customer_gets.value.percentage' must be numeric",
                ) from exc
            if pct < 0 or pct > 100:
                raise AdapterValidationError(
                    self.name,
                    "'customer_gets.value.percentage' must be 0-100",
                )
            effect = {"percentage": pct / 100.0}
        elif "amount" in value:
            try:
                amount_float = float(value["amount"])
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'customer_gets.value.amount' must be numeric",
                ) from exc
            effect = {"amount": amount_float}
        else:
            raise AdapterValidationError(
                self.name,
                "'customer_gets.value' must contain 'percentage' or 'amount'",
            )

        items = self._build_items(
            raw.get("items"), label="customer_gets.items",
        )
        return {
            "value": {
                "discountOnQuantity": {
                    "quantity": str(get_qty),
                    "effect": effect,
                },
            },
            "items": items,
        }

    def _build_items(self, raw: Any, label: str) -> dict[str, Any]:
        # Pattern C from BXGY adapter: items can't be {all: True}
        # for BXGY mutations — must be products or collections.
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                f"'{label}' must be a dict — one of "
                "{'products': [...]} / {'collections': [...]}",
            )
        products = raw.get("products")
        if products is not None:
            if not isinstance(products, list) or not all(
                isinstance(p, str) for p in products
            ):
                raise AdapterValidationError(
                    self.name,
                    f"'{label}.products' must be a list of GID strings",
                )
            return {"products": {
                "productsToAdd": [p.strip() for p in products if p.strip()],
            }}
        collections = raw.get("collections")
        if collections is not None:
            if not isinstance(collections, list) or not all(
                isinstance(c, str) for c in collections
            ):
                raise AdapterValidationError(
                    self.name,
                    f"'{label}.collections' must be a list of GID strings",
                )
            return {"collections": {
                "add": [c.strip() for c in collections if c.strip()],
            }}
        raise AdapterValidationError(
            self.name,
            f"'{label}' must specify 'products' or 'collections'",
        )

    def _build_free_shipping_input(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name, "'title' is required",
            )

        starts_at = params.get("starts_at") or params.get("startsAt")
        if not isinstance(starts_at, str) or not starts_at.strip():
            raise AdapterValidationError(
                self.name, "'starts_at' is required",
            )

        out: dict[str, Any] = {
            "title": title.strip(),
            "startsAt": starts_at.strip(),
        }

        ends_at = params.get("ends_at") or params.get("endsAt")
        if ends_at is not None:
            if not isinstance(ends_at, str):
                raise AdapterValidationError(
                    self.name, "'ends_at' must be a string",
                )
            out["endsAt"] = ends_at.strip()

        # Minimum subtotal (optional).
        minimum_subtotal = params.get("minimum_subtotal")
        if minimum_subtotal is not None:
            try:
                subtotal_float = float(minimum_subtotal)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'minimum_subtotal' must be numeric",
                ) from exc
            out["minimumRequirement"] = {
                "subtotal": {
                    "greaterThanOrEqualToSubtotal": subtotal_float,
                },
            }

        # Destination (default: all countries).
        destination = params.get("destination")
        if destination is None:
            out["destination"] = {"all": True}
        else:
            if not isinstance(destination, dict):
                raise AdapterValidationError(
                    self.name, "'destination' must be a dict",
                )
            if destination.get("all"):
                out["destination"] = {"all": True}
            elif destination.get("countries"):
                countries = destination["countries"]
                if not isinstance(countries, list) or not all(
                    isinstance(c, str) for c in countries
                ):
                    raise AdapterValidationError(
                        self.name,
                        "'destination.countries' must be a list of "
                        "ISO codes",
                    )
                out["destination"] = {"countries": {
                    "add": [c.strip().upper() for c in countries],
                    "includeRestOfWorld": bool(
                        destination.get("include_rest_of_world", False),
                    ),
                }}
            else:
                raise AdapterValidationError(
                    self.name,
                    "'destination' must specify 'all' or 'countries'",
                )

        return out
