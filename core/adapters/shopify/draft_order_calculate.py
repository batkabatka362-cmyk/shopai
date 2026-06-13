"""ShopifyDraftOrderCalculateAdapter — tax/shipping preview without commit.

The pricing engine constantly asks "what would this cart actually
cost the customer?" — base price, applied discounts, shipping rate
for the chosen address, tax based on the destination, total. The
naive answer is to create a draft order and read the totals back,
but every draft order writes a row in the database and counts
against the merchant's draft-order quota.

``draftOrderCalculate`` is Shopify's official preview endpoint: same
``DraftOrderInput``, returns a ``CalculatedDraftOrder`` with all
computed totals — but no row is created, no quota consumed. Engines
can call it dozens of times per cart change without overhead.

Capabilities:

  * ``SHOPIFY_CALCULATE_DRAFT_ORDER`` — preview totals.

Friendly call shape (a subset of DraftOrderInput's most-used fields)::

    {
      "line_items": [
        {"variant_id": "gid://shopify/ProductVariant/1", "quantity": 2},
        {"variant_id": "gid://shopify/ProductVariant/2", "quantity": 1,
         "applied_discount": {
             "value":         "10.00",
             "value_type":    "PERCENTAGE",  # or FIXED_AMOUNT
             "title":         "Loyalty -10%",
             "description":   "VIP customer"}},
      ],
      "customer_id":   "gid://shopify/Customer/123",
      "shipping_address": {
        "address1": "1 Main St", "city": "Seattle",
        "province_code": "WA", "country_code": "US", "zip": "98101"},
      "currency_code": "USD",
      "tags":          "preview,abandoned-cart-flow"
    }

Pattern G note (per CLAUDE.md): money inputs (applied_discount.value)
are coerced inline rather than via a shared utils module — error
messages reference this adapter at the call site.

Pattern F note (per CLAUDE.md): ``draftOrderCalculate.userErrors``
returns ``UserError`` (no ``code`` field), not the ``UserErrors``
variant used by most mutations. Asking for ``code`` rejects the
whole query at validation. Keep the selection to ``field`` /
``message`` only.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_CALCULATED_FIELDS = """
subtotalPriceSet {
  shopMoney { amount currencyCode }
}
totalPriceSet {
  shopMoney { amount currencyCode }
}
totalShippingPriceSet {
  shopMoney { amount currencyCode }
}
totalTaxSet {
  shopMoney { amount currencyCode }
}
currencyCode
shippingLine {
  title
  shippingRateHandle
  price
  custom
}
taxLines {
  title
  rate
  price
}
appliedDiscount {
  title
  description
  value
  valueType
  amountV2 { amount currencyCode }
}
lineItems {
  variant {
    id
    title
  }
  product {
    id
    title
  }
  quantity
  sku
  title
  originalUnitPriceSet {
    shopMoney { amount currencyCode }
  }
  discountedUnitPriceSet {
    shopMoney { amount currencyCode }
  }
  totalDiscountSet {
    shopMoney { amount currencyCode }
  }
}
""".strip()


_CALCULATE_DRAFT_ORDER_MUTATION = f"""
mutation draftOrderCalculate($input: DraftOrderInput!) {{
  draftOrderCalculate(input: $input) {{
    calculatedDraftOrder {{
      {_CALCULATED_FIELDS}
    }}
    userErrors {{
      field
      message
    }}
  }}
}}
""".strip()


_VALID_DISCOUNT_VALUE_TYPES = {"PERCENTAGE", "FIXED_AMOUNT"}


class ShopifyDraftOrderCalculateAdapter(ShopifyBaseAdapter):
    name = "shopify_draft_order_calculate"
    capabilities = {Capability.SHOPIFY_CALCULATE_DRAFT_ORDER}
    required_scopes = frozenset({"read_draft_orders", "write_draft_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_CALCULATE_DRAFT_ORDER:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )
        draft_input = self._build_input(params)
        data = self._gql(_CALCULATE_DRAFT_ORDER_MUTATION, {
            "input": draft_input,
        })
        self._check_user_errors(data, "draftOrderCalculate")
        payload = data.get("draftOrderCalculate") or {}
        return self._success(
            Capability.SHOPIFY_CALCULATE_DRAFT_ORDER,
            data={
                "calculation": self._normalise_calculation(
                    payload.get("calculatedDraftOrder") or {},
                ),
            },
        )

    # ── Input builder ──────────────────────────────────────────────

    @classmethod
    def _build_input(cls, params: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}

        line_items = params.get("line_items") or params.get("lineItems")
        if not isinstance(line_items, list) or not line_items:
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                "'line_items' must be a non-empty list",
            )
        out["lineItems"] = [
            cls._build_line_item(li, i) for i, li in enumerate(line_items)
        ]

        customer_id = params.get("customer_id") or params.get("customerId")
        if customer_id is not None:
            if not isinstance(customer_id, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    "'customer_id' must be a string GID",
                )
            out["purchasingEntity"] = {"customerId": customer_id.strip()}

        shipping_address = params.get("shipping_address") or params.get(
            "shippingAddress"
        )
        if shipping_address is not None:
            out["shippingAddress"] = cls._build_address(
                shipping_address, "shipping_address",
            )

        billing_address = params.get("billing_address") or params.get(
            "billingAddress"
        )
        if billing_address is not None:
            out["billingAddress"] = cls._build_address(
                billing_address, "billing_address",
            )

        email = params.get("email")
        if email is not None:
            if not isinstance(email, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    "'email' must be a string",
                )
            out["email"] = email.strip()

        currency_code = params.get("currency_code") or params.get(
            "presentmentCurrencyCode"
        )
        if currency_code is not None:
            if not isinstance(currency_code, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    "'currency_code' must be a string ISO-4217 code",
                )
            out["presentmentCurrencyCode"] = currency_code.strip().upper()

        note = params.get("note")
        if note is not None:
            if not isinstance(note, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    "'note' must be a string",
                )
            out["note"] = note

        tags = params.get("tags")
        if tags is not None:
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            if not isinstance(tags, list) or not all(
                isinstance(t, str) for t in tags
            ):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    "'tags' must be a string (comma-separated) or list of strings",
                )
            out["tags"] = tags

        # Cart-level discount applies BEFORE per-line discounts in
        # Shopify's tax engine; engines that want one final % off the
        # whole cart pass it here.
        applied_discount = params.get("applied_discount") or params.get(
            "appliedDiscount"
        )
        if applied_discount is not None:
            out["appliedDiscount"] = cls._build_discount(
                applied_discount, "applied_discount",
            )

        # Shipping line override — engines can pre-pick a rate
        # (free / flat / carrier) instead of letting the storefront
        # default kick in.
        shipping_line = params.get("shipping_line") or params.get(
            "shippingLine"
        )
        if shipping_line is not None:
            out["shippingLine"] = cls._build_shipping_line(shipping_line)

        return out

    @classmethod
    def _build_line_item(
        cls, raw: Any, index: int,
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"line_items[{index}] must be a dict",
            )
        out: dict[str, Any] = {}

        variant_id = raw.get("variant_id") or raw.get("variantId")
        if variant_id is not None:
            if not isinstance(variant_id, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    f"line_items[{index}].variant_id must be a string GID",
                )
            out["variantId"] = variant_id.strip()

        title = raw.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    f"line_items[{index}].title must be a string",
                )
            out["title"] = title

        # Either variant_id (catalogue line) or title (custom line) required.
        if "variantId" not in out and "title" not in out:
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"line_items[{index}] needs 'variant_id' or 'title' "
                "(custom line item)",
            )

        quantity = raw.get("quantity")
        if quantity is None:
            quantity = 1
        try:
            quantity_int = int(quantity)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"line_items[{index}].quantity must be an integer",
            ) from exc
        if quantity_int < 1:
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"line_items[{index}].quantity must be >= 1",
            )
        out["quantity"] = quantity_int

        # Custom-line-only price; ignored if variant_id is set.
        original_unit_price = raw.get("original_unit_price") or raw.get(
            "originalUnitPrice"
        )
        if original_unit_price is not None:
            out["originalUnitPrice"] = cls._coerce_money(
                original_unit_price,
                f"line_items[{index}].original_unit_price",
            )

        per_line_discount = raw.get("applied_discount") or raw.get(
            "appliedDiscount"
        )
        if per_line_discount is not None:
            out["appliedDiscount"] = cls._build_discount(
                per_line_discount, f"line_items[{index}].applied_discount",
            )

        return out

    @staticmethod
    def _build_address(raw: Any, label: str) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"'{label}' must be a dict",
            )
        # Shopify's MailingAddressInput fields, snake → camel mapped.
        mapping = {
            "address1": "address1",
            "address2": "address2",
            "city": "city",
            "company": "company",
            "country": "country",
            "country_code": "countryCode",
            "first_name": "firstName",
            "last_name": "lastName",
            "phone": "phone",
            "province": "province",
            "province_code": "provinceCode",
            "zip": "zip",
        }
        out: dict[str, Any] = {}
        for snake, camel in mapping.items():
            value = raw.get(snake) or raw.get(camel)
            if value is None:
                continue
            if not isinstance(value, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    f"'{label}.{snake}' must be a string",
                )
            out[camel] = value.strip()
        return out

    @classmethod
    def _build_discount(cls, raw: Any, label: str) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"'{label}' must be a dict",
            )
        value = raw.get("value")
        if value is None:
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"'{label}.value' is required",
            )
        # W962-66 Pattern G monetary fix: distinguish missing
        # from explicit empty + align default with the sibling
        # apply adapter (PERCENTAGE not FIXED_AMOUNT). Pre-fix
        # the apply path defaulted PERCENTAGE while the
        # calculate path defaulted FIXED_AMOUNT -- the same
        # caller's input would price-quote and then apply
        # differently, breaking trust in the preview-and-apply
        # workflow.
        _MISSING = object()
        vt_snake = raw.get("value_type", _MISSING)
        vt_camel = raw.get("valueType", _MISSING)
        if vt_snake is _MISSING and vt_camel is _MISSING:
            value_type = "PERCENTAGE"
        elif vt_snake is not _MISSING and vt_snake == "":
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"'{label}.value_type' was explicit empty "
                "string. Provide PERCENTAGE or FIXED_AMOUNT, "
                "or omit the key for the default.",
            )
        elif vt_camel is not _MISSING and vt_camel == "":
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"'{label}.valueType' was explicit empty "
                "string. Provide PERCENTAGE or FIXED_AMOUNT, "
                "or omit the key for the default.",
            )
        else:
            value_type = (
                vt_snake if vt_snake is not _MISSING else vt_camel
            )
        if not isinstance(value_type, str):
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"'{label}.value_type' must be a string",
            )
        value_type_upper = value_type.strip().upper()
        if value_type_upper not in _VALID_DISCOUNT_VALUE_TYPES:
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"'{label}.value_type' must be one of: "
                f"{sorted(_VALID_DISCOUNT_VALUE_TYPES)}",
            )

        out: dict[str, Any] = {
            "value": float(cls._coerce_money(value, f"{label}.value")),
            "valueType": value_type_upper,
        }

        title = raw.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    f"'{label}.title' must be a string",
                )
            out["title"] = title

        description = raw.get("description")
        if description is not None:
            if not isinstance(description, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    f"'{label}.description' must be a string",
                )
            out["description"] = description

        return out

    @classmethod
    def _build_shipping_line(cls, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                "'shipping_line' must be a dict",
            )
        out: dict[str, Any] = {}

        title = raw.get("title")
        if title is not None:
            if not isinstance(title, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    "'shipping_line.title' must be a string",
                )
            out["title"] = title

        price = raw.get("price")
        if price is not None:
            out["price"] = cls._coerce_money(
                price, "shipping_line.price",
            )

        rate_handle = raw.get("shipping_rate_handle") or raw.get(
            "shippingRateHandle"
        )
        if rate_handle is not None:
            if not isinstance(rate_handle, str):
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    "'shipping_line.shipping_rate_handle' must be a string",
                )
            out["shippingRateHandle"] = rate_handle

        return out

    @staticmethod
    def _coerce_money(value: Any, label: str) -> str:
        if isinstance(value, str):
            try:
                float(value)
            except ValueError as exc:
                raise AdapterValidationError(
                    "shopify_draft_order_calculate",
                    f"{label} must be numeric, got {value!r}",
                ) from exc
            return value
        if isinstance(value, bool):
            raise AdapterValidationError(
                "shopify_draft_order_calculate",
                f"{label} must be numeric, got bool",
            )
        if isinstance(value, (int, float)):
            return str(value)
        raise AdapterValidationError(
            "shopify_draft_order_calculate",
            f"{label} must be numeric or string-numeric",
        )

    # ── Normalisation ──────────────────────────────────────────────

    @classmethod
    def _normalise_calculation(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        subtotal_amount, subtotal_currency = cls._money(
            node.get("subtotalPriceSet"),
        )
        total_amount, total_currency = cls._money(node.get("totalPriceSet"))
        shipping_amount, _ = cls._money(node.get("totalShippingPriceSet"))
        tax_amount, _ = cls._money(node.get("totalTaxSet"))

        shipping_line = node.get("shippingLine") or {}
        applied_discount = node.get("appliedDiscount") or {}
        applied_discount_amount = (
            (applied_discount.get("amountV2") or {}).get("amount", "")
            if isinstance(applied_discount, dict) else ""
        ) or ""

        tax_lines_raw = node.get("taxLines") or []
        tax_lines = [
            {
                "title": t.get("title", "") or "",
                "rate": float(t.get("rate") or 0),
                "price": str(t.get("price", "") or ""),
            }
            for t in tax_lines_raw if isinstance(t, dict)
        ]

        line_items_raw = node.get("lineItems") or []
        line_items = [
            cls._normalise_line_item(li)
            for li in line_items_raw if isinstance(li, dict)
        ]

        return {
            "subtotal_price": subtotal_amount,
            "total_price": total_amount,
            "total_shipping": shipping_amount,
            "total_tax": tax_amount,
            "currency_code": (
                node.get("currencyCode", "")
                or total_currency
                or subtotal_currency
                or ""
            ),
            "shipping_title": (
                shipping_line.get("title", "")
                if isinstance(shipping_line, dict) else ""
            ) or "",
            "shipping_rate_handle": (
                shipping_line.get("shippingRateHandle", "")
                if isinstance(shipping_line, dict) else ""
            ) or "",
            "shipping_price": (
                str(shipping_line.get("price", "") or "")
                if isinstance(shipping_line, dict) else ""
            ),
            "shipping_custom": bool(
                shipping_line.get("custom", False)
                if isinstance(shipping_line, dict) else False
            ),
            "applied_discount_title": (
                applied_discount.get("title", "")
                if isinstance(applied_discount, dict) else ""
            ) or "",
            "applied_discount_value": str(
                (applied_discount.get("value", "") or "")
                if isinstance(applied_discount, dict) else ""
            ),
            "applied_discount_value_type": (
                applied_discount.get("valueType", "")
                if isinstance(applied_discount, dict) else ""
            ) or "",
            "applied_discount_amount": applied_discount_amount,
            "tax_lines": tax_lines,
            "line_items": line_items,
        }

    @staticmethod
    def _money(envelope: Any) -> tuple[str, str]:
        if not isinstance(envelope, dict):
            return "", ""
        shop_money = envelope.get("shopMoney") or {}
        if not isinstance(shop_money, dict):
            return "", ""
        return (
            shop_money.get("amount", "") or "",
            shop_money.get("currencyCode", "") or "",
        )

    @classmethod
    def _normalise_line_item(cls, node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict):
            return {}
        original_amount, _ = cls._money(node.get("originalUnitPriceSet"))
        discounted_amount, _ = cls._money(node.get("discountedUnitPriceSet"))
        total_discount, _ = cls._money(node.get("totalDiscountSet"))
        variant = node.get("variant") or {}
        product = node.get("product") or {}
        return {
            "title": node.get("title", "") or "",
            "sku": node.get("sku", "") or "",
            "quantity": int(node.get("quantity") or 0),
            "variant_id": (
                variant.get("id", "")
                if isinstance(variant, dict) else ""
            ) or "",
            "variant_title": (
                variant.get("title", "")
                if isinstance(variant, dict) else ""
            ) or "",
            "product_id": (
                product.get("id", "")
                if isinstance(product, dict) else ""
            ) or "",
            "product_title": (
                product.get("title", "")
                if isinstance(product, dict) else ""
            ) or "",
            "original_unit_price": original_amount,
            "discounted_unit_price": discounted_amount,
            "total_discount": total_discount,
        }
