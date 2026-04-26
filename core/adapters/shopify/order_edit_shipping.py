"""ShopifyOrderEditShippingAdapter — shipping-only post-purchase edits.

The existing ``order_edits.py`` adapter wraps line-item edits
(add_variant / add_custom_item / set_quantity / add_line_item_discount)
inside a single SHOPIFY_EDIT_ORDER call by running the full
begin → ops → commit cycle. This adapter is the SHIPPING-LINE
counterpart — wraps the same begin → mutate → commit envelope but
specifically for shipping-line ops (add a shipping fee, change the
title or price, remove a shipping line entirely).

ShopAI's recovery + customer-service automations write these:

  * Customer service issues a free-shipping refund retroactively →
    update_shipping_line with price 0 (the original shipping fee is
    refunded back to the customer).
  * Carrier reprices in transit → update_shipping_line with a new
    price; the customer is debited or refunded the difference.
  * Add a fee for a special-delivery option after the customer
    requested it post-purchase.
  * Remove an erroneously-charged express line and re-bill manually.

Capabilities:

  * ``SHOPIFY_ORDER_EDIT_ADD_SHIPPING_LINE``    — full cycle:
    orderEditBegin → orderEditAddShippingLine → orderEditCommit.
  * ``SHOPIFY_ORDER_EDIT_UPDATE_SHIPPING_LINE`` — full cycle with
    update.
  * ``SHOPIFY_ORDER_EDIT_REMOVE_SHIPPING_LINE`` — full cycle with
    remove.

Each capability takes a LIVE order id (``order_id``) and an
optional ``shipping_line_id`` (required for update/remove). The
adapter handles the begin → op → commit transaction internally; if
the intermediate op fails the calculated order is discarded
without committing.

Friendly call shape (add)::

    {"order_id":         "gid://shopify/Order/123",
     "title":            "Special delivery",
     "price":            "12.50",
     "currency_code":    "USD",     # optional, default USD
     "notify_customer":  False,     # optional, applied at commit
     "staff_note":       "Added per customer request"}

Pattern A — id at field level on every mutation (orderEditBegin,
orderEditAddShippingLine, orderEditCommit, etc.).

Pattern F — every mutation in the orderEdit family uses the bare
``UserError`` type (no ``code``); already documented in CLAUDE.md
under the order_edits adapter.

Pattern G — money input inlined per adapter.
"""
from __future__ import annotations

from typing import Any

from ..base import Capability
from ..errors import AdapterValidationError
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


_ADD_SHIPPING_LINE_MUTATION = """
mutation orderEditAddShippingLine(
  $id: ID!,
  $shippingLine: OrderEditAddShippingLineInput!
) {
  orderEditAddShippingLine(
    id: $id, shippingLine: $shippingLine
  ) {
    calculatedShippingLine {
      id
      title
      price {
        shopMoney {
          amount
          currencyCode
        }
      }
      stagedStatus
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_UPDATE_SHIPPING_LINE_MUTATION = """
mutation orderEditUpdateShippingLine(
  $id: ID!,
  $shippingLineId: ID!,
  $shippingLine: OrderEditUpdateShippingLineInput!
) {
  orderEditUpdateShippingLine(
    id: $id,
    shippingLineId: $shippingLineId,
    shippingLine: $shippingLine
  ) {
    calculatedShippingLine {
      id
      title
      price {
        shopMoney {
          amount
          currencyCode
        }
      }
      stagedStatus
    }
    userErrors {
      field
      message
    }
  }
}
""".strip()


_REMOVE_SHIPPING_LINE_MUTATION = """
mutation orderEditRemoveShippingLine(
  $id: ID!,
  $shippingLineId: ID!
) {
  orderEditRemoveShippingLine(
    id: $id, shippingLineId: $shippingLineId
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
  $id: ID!,
  $notifyCustomer: Boolean,
  $staffNote: String
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


_DEFAULT_CURRENCY = "USD"


class ShopifyOrderEditShippingAdapter(ShopifyBaseAdapter):
    name = "shopify_order_edit_shipping"
    capabilities = {
        Capability.SHOPIFY_ORDER_EDIT_ADD_SHIPPING_LINE,
        Capability.SHOPIFY_ORDER_EDIT_UPDATE_SHIPPING_LINE,
        Capability.SHOPIFY_ORDER_EDIT_REMOVE_SHIPPING_LINE,
    }

    def _execute(
        self,
        capability: Capability,
        params: dict[str, Any],
    ) -> Any:
        if capability == \
                Capability.SHOPIFY_ORDER_EDIT_ADD_SHIPPING_LINE:
            return self._add(params)
        if capability == \
                Capability.SHOPIFY_ORDER_EDIT_UPDATE_SHIPPING_LINE:
            return self._update(params)
        if capability == \
                Capability.SHOPIFY_ORDER_EDIT_REMOVE_SHIPPING_LINE:
            return self._remove(params)
        raise AdapterValidationError(
            self.name, f"unsupported capability: {capability.value}",
        )

    # ── Add ────────────────────────────────────────────────────────

    def _add(self, params: dict[str, Any]) -> Any:
        order_id = self._extract_order_id(params)
        title = params.get("title")
        if not isinstance(title, str) or not title.strip():
            raise AdapterValidationError(
                self.name,
                "'title' is required (the shipping line label "
                "shown on the customer's invoice)",
            )
        price = self._money_input(params, "price")

        calc_id = self._begin(order_id)
        op_data = self._gql(_ADD_SHIPPING_LINE_MUTATION, {
            "id": calc_id,
            "shippingLine": {
                "title": title.strip(),
                "price": price,
            },
        })
        self._check_user_errors(op_data, "orderEditAddShippingLine")
        line_node = (
            (op_data.get("orderEditAddShippingLine") or {})
            .get("calculatedShippingLine")
            or {}
        )

        commit = self._commit(calc_id, params)
        return self._success(
            Capability.SHOPIFY_ORDER_EDIT_ADD_SHIPPING_LINE,
            data={
                "order_id": commit.get("order_id", "") or order_id,
                "order_name": commit.get("order_name", ""),
                "shipping_line": self._normalise_line(line_node),
                "total_price": commit.get("total_price", 0.0),
                "currency_code": commit.get("currency_code", ""),
            },
        )

    # ── Update ─────────────────────────────────────────────────────

    def _update(self, params: dict[str, Any]) -> Any:
        order_id = self._extract_order_id(params)
        shipping_line_id = self._extract_shipping_line_id(params)
        body = self._build_update_body(params)
        if not body:
            raise AdapterValidationError(
                self.name,
                "supply at least one of 'title' / 'price'",
            )

        calc_id = self._begin(order_id)
        op_data = self._gql(_UPDATE_SHIPPING_LINE_MUTATION, {
            "id": calc_id,
            "shippingLineId": shipping_line_id,
            "shippingLine": body,
        })
        self._check_user_errors(op_data, "orderEditUpdateShippingLine")
        line_node = (
            (op_data.get("orderEditUpdateShippingLine") or {})
            .get("calculatedShippingLine")
            or {}
        )

        commit = self._commit(calc_id, params)
        return self._success(
            Capability.SHOPIFY_ORDER_EDIT_UPDATE_SHIPPING_LINE,
            data={
                "order_id": commit.get("order_id", "") or order_id,
                "order_name": commit.get("order_name", ""),
                "shipping_line": self._normalise_line(line_node),
                "total_price": commit.get("total_price", 0.0),
                "currency_code": commit.get("currency_code", ""),
            },
        )

    # ── Remove ─────────────────────────────────────────────────────

    def _remove(self, params: dict[str, Any]) -> Any:
        order_id = self._extract_order_id(params)
        shipping_line_id = self._extract_shipping_line_id(params)

        calc_id = self._begin(order_id)
        op_data = self._gql(_REMOVE_SHIPPING_LINE_MUTATION, {
            "id": calc_id,
            "shippingLineId": shipping_line_id,
        })
        self._check_user_errors(op_data, "orderEditRemoveShippingLine")

        commit = self._commit(calc_id, params)
        return self._success(
            Capability.SHOPIFY_ORDER_EDIT_REMOVE_SHIPPING_LINE,
            data={
                "order_id": commit.get("order_id", "") or order_id,
                "order_name": commit.get("order_name", ""),
                "removed_shipping_line_id": shipping_line_id,
                "total_price": commit.get("total_price", 0.0),
                "currency_code": commit.get("currency_code", ""),
            },
        )

    # ── Begin / commit helpers ─────────────────────────────────────

    def _begin(self, order_id: str) -> str:
        data = self._gql(_BEGIN_MUTATION, {"id": order_id})
        self._check_user_errors(data, "orderEditBegin")
        calc = (
            (data.get("orderEditBegin") or {}).get("calculatedOrder")
            or {}
        )
        calc_id = calc.get("id", "")
        if not calc_id:
            raise AdapterValidationError(
                self.name,
                "orderEditBegin returned no calculatedOrder.id",
            )
        return calc_id

    def _commit(
        self, calc_id: str, params: dict[str, Any],
    ) -> dict[str, Any]:
        notify = params.get("notify_customer")
        if "notify_customer" not in params and \
                "notifyCustomer" in params:
            notify = params["notifyCustomer"]
        staff_note = (
            params.get("staff_note") or params.get("staffNote")
        )

        commit_data = self._gql(_COMMIT_MUTATION, {
            "id": calc_id,
            "notifyCustomer": (
                bool(notify) if notify is not None else None
            ),
            "staffNote": (
                staff_note.strip() if isinstance(staff_note, str)
                and staff_note.strip() else None
            ),
        })
        self._check_user_errors(commit_data, "orderEditCommit")
        order = (commit_data.get("orderEditCommit") or {}).get(
            "order",
        ) or {}
        total = (order.get("totalPriceSet") or {}).get(
            "presentmentMoney",
        ) or {}
        try:
            total_amount = float(total.get("amount", 0) or 0)
        except (TypeError, ValueError):
            total_amount = 0.0
        return {
            "order_id": order.get("id", "") or "",
            "order_name": order.get("name", "") or "",
            "total_price": total_amount,
            "currency_code": total.get("currencyCode", "") or "",
        }

    # ── Build helpers ──────────────────────────────────────────────

    def _extract_order_id(self, params: dict[str, Any]) -> str:
        order_id = (
            params.get("order_id")
            or params.get("orderId")
            or params.get("id")
        )
        if not isinstance(order_id, str) or not order_id.strip():
            raise AdapterValidationError(
                self.name,
                "'order_id' (Shopify GID for the live Order) is "
                "required",
            )
        return order_id.strip()

    def _extract_shipping_line_id(
        self, params: dict[str, Any],
    ) -> str:
        line_id = (
            params.get("shipping_line_id")
            or params.get("shippingLineId")
        )
        if not isinstance(line_id, str) or not line_id.strip():
            raise AdapterValidationError(
                self.name,
                "'shipping_line_id' (the existing shipping line "
                "GID on the order) is required for update / remove",
            )
        return line_id.strip()

    def _build_update_body(
        self, params: dict[str, Any],
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        title = params.get("title")
        if title is not None:
            if not isinstance(title, str) or not title.strip():
                raise AdapterValidationError(
                    self.name, "'title' must be a non-empty string",
                )
            out["title"] = title.strip()
        if "price" in params and params["price"] is not None:
            out["price"] = self._money_input(params, "price")
        return out

    def _money_input(
        self, params: dict[str, Any], key: str,
    ) -> dict[str, Any]:
        raw = params.get(key)
        if raw is None:
            raise AdapterValidationError(
                self.name, f"'{key}' is required",
            )
        if isinstance(raw, dict):
            amount = raw.get("amount")
            currency = (
                raw.get("currency_code")
                or raw.get("currencyCode")
                or _DEFAULT_CURRENCY
            )
        else:
            amount = raw
            currency = (
                params.get("currency_code")
                or params.get("currencyCode")
                or _DEFAULT_CURRENCY
            )
        try:
            amount_float = float(amount)
        except (TypeError, ValueError) as exc:
            raise AdapterValidationError(
                self.name, f"'{key}' amount must be numeric",
            ) from exc
        if amount_float < 0:
            raise AdapterValidationError(
                self.name, f"'{key}' amount must be >= 0",
            )
        if not isinstance(currency, str) or not currency.strip():
            raise AdapterValidationError(
                self.name, f"'{key}' currency_code must be a string",
            )
        return {
            "amount": amount_float,
            "currencyCode": currency.strip().upper(),
        }

    @staticmethod
    def _normalise_line(node: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(node, dict) or not node:
            return {}
        price = (node.get("price") or {}).get("shopMoney") or {}
        try:
            amount = float(price.get("amount", 0) or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return {
            "id": node.get("id", "") or "",
            "title": node.get("title", "") or "",
            "amount": amount,
            "currency_code": price.get("currencyCode", "") or "",
            "staged_status": node.get("stagedStatus", "") or "",
        }
