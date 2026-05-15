"""ShopifyDiscountCodeBxgyAdapter — buy-x-get-y code discounts.

Companion to ``discounts.py`` (BASIC code-based percentage/amount
discounts) and ``discount_automatic.py`` (automatic site-wide
discounts). This adapter is the third leg: BUY-X-GET-Y code-based
offers ("Use code BUNDLE3, buy 2 lanterns get the 3rd 50% off").

ShopAI's pricing + merchandising engines use these for:

  * Bundle promotions ("buy 2 of category A, get 1 of category B
    at $5 off").
  * Tiered loyalty rewards ("buy any 3 items from the SS26
    collection, the cheapest is free").
  * Influencer-specific BXGY codes ("INFLUENCER10 — buy any
    skincare, get a free travel-sized cleanser").

Capabilities (CRUD on the BXGY type — list / get share the
codeDiscountNodes connection from discounts.py and don't need
separate caps here):

  * ``SHOPIFY_CREATE_DISCOUNT_BXGY`` — create a buy-x-get-y code.
  * ``SHOPIFY_DELETE_DISCOUNT_BXGY`` — delete by GID. Reuses the
    same discountCodeDelete mutation discounts.py uses (the
    delete is type-agnostic).

Friendly create call shape::

    {"title":          "Bundle Pack",
     "code":           "BUNDLE3",
     "starts_at":      "2026-04-26T00:00:00Z",
     "ends_at":        "2026-12-31T23:59:59Z",
     "uses_per_order_limit": 1,
     "customer_gets": {
        "value": {"percentage": 50},   # or {"amount": "5.00"}
        "items": {"all": True},        # or {"products": [GID, ...]}
        "quantity": 1                  # how many "Y" items get
     },
     "customer_buys": {
        "value": {"quantity": 2},      # how many "X" items needed
        "items": {"all": True}         # or {"collections": [GID]}
     }}

Pattern A: variable name ``bxgyCodeDiscount`` matches the input
type. Same convention as discounts.py / validations.py.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CREATE_BXGY_MUTATION = """
mutation discountCodeBxgyCreate(
  $bxgyCodeDiscount: DiscountCodeBxgyInput!
) {
  discountCodeBxgyCreate(bxgyCodeDiscount: $bxgyCodeDiscount) {
    codeDiscountNode {
      id
      codeDiscount {
        ... on DiscountCodeBxgy {
          title
          summary
          status
          startsAt
          endsAt
          usesPerOrderLimit
          customerBuys {
            value {
              ... on DiscountQuantity {
                quantity
              }
            }
          }
          customerGets {
            value {
              ... on DiscountOnQuantity {
                quantity {
                  quantity
                }
                effect {
                  ... on DiscountPercentage {
                    percentage
                  }
                }
              }
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


class ShopifyDiscountCodeBxgyAdapter(ShopifyBaseAdapter):
    name = "shopify_discount_code_bxgy"
    capabilities = {
        Capability.SHOPIFY_CREATE_DISCOUNT_BXGY,
        Capability.SHOPIFY_DELETE_DISCOUNT_BXGY,
    }
    required_scopes = frozenset({"write_discounts"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == Capability.SHOPIFY_CREATE_DISCOUNT_BXGY:
            return self._create(params)
        if capability == Capability.SHOPIFY_DELETE_DISCOUNT_BXGY:
            return self._delete(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Create ─────────────────────────────────────────────────────

    def _create(self, params: dict[str, Any]) -> Any:
        discount_input = self._build_input(params)
        data = self._gql(_CREATE_BXGY_MUTATION, {
            "bxgyCodeDiscount": discount_input,
        })
        self._check_user_errors(data, "discountCodeBxgyCreate")
        payload = data.get("discountCodeBxgyCreate") or {}
        node = payload.get("codeDiscountNode") or {}
        discount = node.get("codeDiscount") or {}
        codes_raw = (discount.get("codes") or {}).get("edges") or []
        codes = [
            (e.get("node") or {}).get("code", "") or ""
            for e in codes_raw if isinstance(e, dict)
        ]
        return self._success(
            Capability.SHOPIFY_CREATE_DISCOUNT_BXGY,
            data={
                "id": node.get("id", "") or "",
                "title": discount.get("title", "") or "",
                "status": discount.get("status", "") or "",
                "starts_at": discount.get("startsAt", "") or "",
                "ends_at": discount.get("endsAt", "") or "",
                "uses_per_order_limit": int(
                    discount.get("usesPerOrderLimit") or 0,
                ) or 0,
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
            Capability.SHOPIFY_DELETE_DISCOUNT_BXGY,
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

        usage_limit = params.get("usage_limit") or params.get("usageLimit")
        if usage_limit is not None:
            try:
                out["usageLimit"] = int(usage_limit)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    self.name,
                    "'usage_limit' must be an integer",
                ) from exc

        out["customerBuys"] = self._build_customer_buys(
            params.get("customer_buys") or params.get("customerBuys"),
        )
        out["customerGets"] = self._build_customer_gets(
            params.get("customer_gets") or params.get("customerGets"),
        )

        # customerSelection is REQUIRED on every BXGY mutation (Shopify
        # rejects the create with "Customer selection can't be blank"
        # if missing). Default to "all customers" so engines that don't
        # pass anything get the standard public-facing discount.
        customer_selection = params.get("customer_selection") or params.get(
            "customerSelection"
        )
        if customer_selection is None:
            out["customerSelection"] = {"all": True}
        else:
            out["customerSelection"] = self._build_customer_selection(
                customer_selection,
            )

        return out

    def _build_customer_selection(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'customer_selection' must be a dict — one of "
                "{'all': True} / {'customers': [...]}",
            )
        if raw.get("all"):
            return {"all": True}
        customer_ids = raw.get("customers") or raw.get("customer_ids")
        if customer_ids is not None:
            if not isinstance(customer_ids, list) or not all(
                isinstance(c, str) for c in customer_ids
            ):
                raise AdapterValidationError(
                    self.name,
                    "'customer_selection.customers' must be a list of GIDs",
                )
            return {"customers": {
                "add": [c.strip() for c in customer_ids if c.strip()],
            }}
        raise AdapterValidationError(
            self.name,
            "'customer_selection' must specify 'all' or 'customers'",
        )

    def _build_customer_buys(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'customer_buys' is required (the X side: items + quantity)",
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
        return {
            "value": {"quantity": str(qty)},
            "items": items,
        }

    def _build_customer_gets(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                "'customer_gets' is required (the Y side: items + value)",
            )

        value = raw.get("value")
        if not isinstance(value, dict):
            raise AdapterValidationError(
                self.name,
                "'customer_gets.value' must be a dict (percentage / amount / quantity)",
            )

        # The Y side is always a "discount on quantity" — N items get
        # an effect (% off / $ off / free).
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

        # Effect = percentage OR fixed amount.
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
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                self.name,
                f"'{label}' must be a dict — one of "
                "{'all': True} / {'products': [...]} / {'collections': [...]}",
            )
        if raw.get("all"):
            return {"all": True}
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
            f"'{label}' must specify 'all', 'products', or 'collections'",
        )
