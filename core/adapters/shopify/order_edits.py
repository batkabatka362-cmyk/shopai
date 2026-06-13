"""ShopifyOrderEditsAdapter — post-purchase modifications.

Customer service automation often needs to fix an existing order:
swap a wrong variant, add a missed item, change a quantity, or apply
a make-good discount before shipping. Shopify exposes order editing
as a stateful 3-stage GraphQL flow:

    orderEditBegin(orderId)          → calculatedOrder.id
    orderEditAddVariant(...)         | many of these
    orderEditAddCustomItem(...)      | run against the
    orderEditSetQuantity(...)        | calculatedOrder
    orderEditAddLineItemDiscount(...) | (each is its own mutation)
    orderEditCommit(calculatedId)    → finalised Order

That stateful flow doesn't fit the single-call adapter pattern the
rest of ShopAI uses. The wrapper here folds the whole sequence into
one ``SHOPIFY_EDIT_ORDER`` call: callers describe their intent as a
list of high-level operations and the adapter handles begin →
mutations → commit. If any intermediate mutation fails the adapter
surfaces the error WITHOUT committing — Shopify's calculated-order
state is discarded automatically when the GraphQL session ends, so
there's no half-applied edit to clean up.

Capability:

  * ``SHOPIFY_EDIT_ORDER`` — apply 1..N changes to an order in one
    transactional batch.

Friendly call shape::

    {
      "order_id": "gid://shopify/Order/123",
      "changes": [
          {"op": "add_variant",
           "variant_id": "gid://shopify/ProductVariant/9",
           "quantity": 1},
          {"op": "set_quantity",
           "line_item_id": "gid://shopify/CalculatedLineItem/x",
           "quantity": 0,           # 0 == remove
           "restock": True},
          {"op": "add_custom_item",
           "title": "Make-good gift",
           "price": "0.00",
           "quantity": 1,
           "taxable": False},
          {"op": "add_line_item_discount",
           "line_item_id": "gid://shopify/CalculatedLineItem/y",
           "value_type": "PERCENTAGE",
           "value": 15,
           "description": "Apology discount"},
      ],
      "notify_customer": True,        # email the updated invoice
      "staff_note": "Made up for the wrong-color shipment.",
    }

Order edits operate on *calculated* line items, not the original
order's line items — Shopify's begin step takes a snapshot, the
mutations modify the snapshot, and commit replaces the live order
with the snapshot. Engines that need to modify an existing line
must capture its calculatedLineItem id from a prior fetch (or
inspect the begin response, which the adapter exposes via
``calculated_order_id`` for advanced workflows).
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterError, AdapterValidationError
from ._base import ShopifyBaseAdapter


# ── GraphQL templates ───────────────────────────────────────────────


_BEGIN_MUTATION = """
mutation orderEditBegin($id: ID!) {
  orderEditBegin(id: $id) {
    calculatedOrder {
      id
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_ADD_VARIANT_MUTATION = """
mutation orderEditAddVariant($id: ID!, $variantId: ID!, $quantity: Int!) {
  orderEditAddVariant(id: $id, variantId: $variantId, quantity: $quantity) {
    calculatedOrder {
      id
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_ADD_CUSTOM_ITEM_MUTATION = """
mutation orderEditAddCustomItem(
  $id: ID!, $title: String!, $price: MoneyInput!,
  $quantity: Int!, $taxable: Boolean, $requiresShipping: Boolean
) {
  orderEditAddCustomItem(
    id: $id, title: $title, price: $price,
    quantity: $quantity, taxable: $taxable,
    requiresShipping: $requiresShipping
  ) {
    calculatedOrder {
      id
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_SET_QUANTITY_MUTATION = """
mutation orderEditSetQuantity(
  $id: ID!, $lineItemId: ID!, $quantity: Int!, $restock: Boolean
) {
  orderEditSetQuantity(
    id: $id, lineItemId: $lineItemId, quantity: $quantity, restock: $restock
  ) {
    calculatedOrder {
      id
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_ADD_LINE_DISCOUNT_MUTATION = """
mutation orderEditAddLineItemDiscount(
  $id: ID!, $lineItemId: ID!, $discount: OrderEditAppliedDiscountInput!
) {
  orderEditAddLineItemDiscount(
    id: $id, lineItemId: $lineItemId, discount: $discount
  ) {
    calculatedOrder {
      id
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_COMMIT_MUTATION = """
mutation orderEditCommit(
  $id: ID!, $notifyCustomer: Boolean, $staffNote: String
) {
  orderEditCommit(
    id: $id, notifyCustomer: $notifyCustomer, staffNote: $staffNote
  ) {
    order {
      id
      name
      totalPriceSet {
        presentmentMoney {
          amount
          currencyCode
        }
      }
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


# Allowed operation kinds. Each maps to a builder that turns the
# friendly dict into the GraphQL mutation + variables tuple.
_VALID_OPS = {
    "add_variant",
    "add_custom_item",
    "set_quantity",
    "add_line_item_discount",
}


class ShopifyOrderEditsAdapter(ShopifyBaseAdapter):
    name = "shopify_order_edits"
    capabilities = {Capability.SHOPIFY_EDIT_ORDER}
    required_scopes = frozenset({"write_orders"})

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability != Capability.SHOPIFY_EDIT_ORDER:
            raise AdapterValidationError(
                self.name, f"unsupported capability: {capability.value}",
            )

        order_id = params.get("order_id") or params.get("id")
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'order_id' (Shopify GID for the order) is required",
            )

        changes = params.get("changes")
        if not isinstance(changes, list) or not changes:
            raise AdapterValidationError(
                self.name,
                "'changes' must be a non-empty list of operations",
            )

        # Validate every change up-front so we never call begin only
        # to fail on a malformed change halfway through. Validation
        # builds the Shopify variables dict per change so the actual
        # apply step is just dispatch.
        prepared = [
            self._build_change(c, i) for i, c in enumerate(changes)
        ]

        notify_customer = bool(params.get("notify_customer", False))
        staff_note = params.get("staff_note")
        if staff_note is not None and not isinstance(staff_note, str):
            raise AdapterValidationError(
                self.name, "'staff_note' must be a string",
            )

        # ── Stage 1: begin ──
        begin_data = self._gql(_BEGIN_MUTATION, {"id": order_id.strip()})
        self._check_user_errors(begin_data, "orderEditBegin")
        calc_order = (
            (begin_data.get("orderEditBegin") or {}).get("calculatedOrder") or {}
        )
        calc_id = calc_order.get("id")
        if not isinstance(calc_id, str) or not calc_id:
            raise AdapterError(
                self.name,
                "orderEditBegin returned no calculatedOrder.id",
            )

        # ── Stage 2: apply each change ──
        # If any change fails (userErrors or transport error), bail
        # out without committing — Shopify discards the in-progress
        # calculated order on session end, so there's no half-applied
        # state to clean up.
        applied: list[dict[str, Any]] = []
        for change in prepared:
            mutation = change["mutation"]
            variables = change["variables"]
            variables["id"] = calc_id  # always against the calc order
            mut_data = self._gql(mutation, variables)
            self._check_user_errors(mut_data, change["mutation_name"])
            applied.append({"op": change["op"], "ok": True})

        # ── Stage 3: commit ──
        commit_vars: dict[str, Any] = {
            "id": calc_id,
            "notifyCustomer": notify_customer,
        }
        if staff_note:
            commit_vars["staffNote"] = staff_note
        commit_data = self._gql(_COMMIT_MUTATION, commit_vars)
        self._check_user_errors(commit_data, "orderEditCommit")
        order = (
            (commit_data.get("orderEditCommit") or {}).get("order") or {}
        )
        total_field = order.get("totalPriceSet") or {}
        total_money = (
            total_field.get("presentmentMoney")
            if isinstance(total_field, dict) else None
        ) or {}
        try:
            total_amount = float(total_money.get("amount", 0) or 0)
        except (TypeError, ValueError):
            total_amount = 0.0

        return self._success(
            Capability.SHOPIFY_EDIT_ORDER,
            data={
                "order_id": order.get("id", "") or "",
                "order_name": order.get("name", "") or "",
                "calculated_order_id": calc_id,
                "applied_changes": applied,
                "change_count": len(applied),
                "new_total": total_amount,
                "currency": total_money.get("currencyCode", "") or "",
                "notified_customer": notify_customer,
            },
        )

    @staticmethod
    def _build_change(change: Any, idx: int) -> dict[str, Any]:
        """Validate a single change dict and produce the (mutation,
        variables, mutation_name) tuple needed to apply it.

        Raises AdapterValidationError on every malformed-input shape
        so the whole batch fails fast instead of begin-ing an edit
        that we can't apply.
        """
        if not isinstance(change, dict):
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] must be a dict",
            )
        op = change.get("op")
        if op not in _VALID_OPS:
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] 'op' must be one of {sorted(_VALID_OPS)}, "
                f"got {op!r}",
            )

        if op == "add_variant":
            variant_id = change.get("variant_id") or change.get("variantId")
            quantity = change.get("quantity", 1)
            if not isinstance(variant_id, str) or not variant_id.strip():
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] add_variant needs 'variant_id'",
                )
            try:
                qty = int(quantity)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] 'quantity' must be int",
                ) from exc
            if qty < 1:
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] add_variant 'quantity' must be >= 1",
                )
            return {
                "op": op,
                "mutation": _ADD_VARIANT_MUTATION,
                "mutation_name": "orderEditAddVariant",
                "variables": {
                    "variantId": variant_id.strip(),
                    "quantity": qty,
                },
            }

        if op == "add_custom_item":
            title = change.get("title")
            price = change.get("price")
            quantity = change.get("quantity", 1)
            if not isinstance(title, str) or not title.strip():
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] add_custom_item needs 'title'",
                )
            if price is None:
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] add_custom_item needs 'price'",
                )
            try:
                qty = int(quantity)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] 'quantity' must be int",
                ) from exc
            if qty < 1:
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] 'quantity' must be >= 1",
                )
            taxable = bool(change.get("taxable", True))
            requires_shipping = bool(change.get("requires_shipping", True))
            return {
                "op": op,
                "mutation": _ADD_CUSTOM_ITEM_MUTATION,
                "mutation_name": "orderEditAddCustomItem",
                "variables": {
                    "title": title.strip(),
                    "price": _money_input(price, where=f"changes[{idx}].price"),
                    "quantity": qty,
                    "taxable": taxable,
                    "requiresShipping": requires_shipping,
                },
            }

        if op == "set_quantity":
            line_id = change.get("line_item_id") or change.get("lineItemId")
            quantity = change.get("quantity")
            if not isinstance(line_id, str) or not line_id.strip():
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] set_quantity needs 'line_item_id'",
                )
            if quantity is None:
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] set_quantity needs 'quantity' "
                    f"(0 == remove the line)",
                )
            try:
                qty = int(quantity)
            except (TypeError, ValueError) as exc:
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] 'quantity' must be int",
                ) from exc
            if qty < 0:
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] 'quantity' must be >= 0",
                )
            restock = bool(change.get("restock", True))
            return {
                "op": op,
                "mutation": _SET_QUANTITY_MUTATION,
                "mutation_name": "orderEditSetQuantity",
                "variables": {
                    "lineItemId": line_id.strip(),
                    "quantity": qty,
                    "restock": restock,
                },
            }

        # op == "add_line_item_discount"
        line_id = change.get("line_item_id") or change.get("lineItemId")
        if not isinstance(line_id, str) or not line_id.strip():
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] add_line_item_discount needs 'line_item_id'",
            )
        # W962-66 Pattern G monetary fix: distinguish missing
        # from explicit empty.
        _MISSING = object()
        vt_snake = change.get("value_type", _MISSING)
        vt_camel = change.get("valueType", _MISSING)
        if vt_snake is _MISSING and vt_camel is _MISSING:
            value_type = "PERCENTAGE"
        elif vt_snake is not _MISSING and vt_snake == "":
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] 'value_type' was explicit "
                "empty string. Provide PERCENTAGE or "
                "FIXED_AMOUNT, or omit for default.",
            )
        elif vt_camel is not _MISSING and vt_camel == "":
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] 'valueType' was explicit "
                "empty string. Provide PERCENTAGE or "
                "FIXED_AMOUNT, or omit for default.",
            )
        else:
            value_type = (
                vt_snake if vt_snake is not _MISSING else vt_camel
            )
        if not isinstance(value_type, str):
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] 'value_type' must be a string",
            )
        value_type = value_type.upper()
        if value_type not in {"PERCENTAGE", "FIXED_AMOUNT"}:
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] 'value_type' must be PERCENTAGE or "
                f"FIXED_AMOUNT, got {value_type!r}",
            )
        value = change.get("value")
        try:
            value_num = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] 'value' must be numeric",
            ) from exc
        if value_num <= 0:
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] 'value' must be > 0",
            )
        if value_type == "PERCENTAGE" and value_num > 100:
            raise AdapterValidationError(
                "shopify_order_edits",
                f"changes[{idx}] PERCENTAGE 'value' must be <= 100",
            )
        discount: dict[str, Any] = {
            "value": value_num,
            "valueType": value_type,
        }
        description = change.get("description")
        if description:
            if not isinstance(description, str):
                raise AdapterValidationError(
                    "shopify_order_edits",
                    f"changes[{idx}] 'description' must be a string",
                )
            discount["description"] = description
        return {
            "op": op,
            "mutation": _ADD_LINE_DISCOUNT_MUTATION,
            "mutation_name": "orderEditAddLineItemDiscount",
            "variables": {
                "lineItemId": line_id.strip(),
                "discount": discount,
            },
        }


def _money_input(raw: Any, *, where: str) -> dict[str, Any]:
    """Same money-coerce helper used by the marketing adapter; copied
    here rather than imported because the symmetric "every adapter
    that takes money has its own coercer" stays simpler than a
    shared utils module that would need its own test surface."""
    if isinstance(raw, (int, float)):
        return {"amount": f"{float(raw):.2f}", "currencyCode": "USD"}
    if not isinstance(raw, dict):
        raise AdapterValidationError(
            "shopify_order_edits",
            f"{where!r} must be {{amount, currency}} or a bare number",
        )
    amount = raw.get("amount")
    if amount is None:
        raise AdapterValidationError(
            "shopify_order_edits", f"{where!r} missing 'amount'",
        )
    try:
        amt = float(amount)
    except (TypeError, ValueError) as exc:
        raise AdapterValidationError(
            "shopify_order_edits",
            f"{where!r} 'amount' must be numeric",
        ) from exc
    if amt < 0:
        raise AdapterValidationError(
            "shopify_order_edits",
            f"{where!r} 'amount' must be >= 0",
        )
    currency = raw.get("currency") or raw.get("currencyCode") or "USD"
    if not isinstance(currency, str):
        raise AdapterValidationError(
            "shopify_order_edits",
            f"{where!r} 'currency' must be a string",
        )
    return {"amount": f"{amt:.2f}", "currencyCode": currency.upper()}
