"""Shopify discounts — price rules + discount codes.

Shopify's discount model is two-step:

  1. **Price Rule** — the semantic of the discount (10% off
     all products, $5 off orders over $50, BOGO, etc.).
     Created first, referenced by its ``id``.
  2. **Discount Code** — the string customers type at
     checkout. One price rule can have many codes (rare but
     supported). Created under
     ``price_rules/{rule_id}/discount_codes.json``.

Convenience method ``create_percentage_code`` bundles both
steps into one call for the common case ("I want code
SUMMER20 = 20% off everything, one per customer, expires in
14 days"). Raw create/update/get methods remain for edge
cases.

All methods take a ``ShopifyAdminClient``. No singleton.
Tests pass a fake client + assert the expected REST calls.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger("shopai.shopify_admin.discounts")


#: Price rule ``value_type`` choices Shopify accepts.
VALUE_TYPE_PERCENTAGE = "percentage"
VALUE_TYPE_FIXED_AMOUNT = "fixed_amount"


class Discounts:
    """Stateless discount CRUD. Every method is a
    ``@staticmethod`` so callers don't have to instantiate."""

    # ── Price rules ─────────────────────────────────────

    @staticmethod
    def list_price_rules(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = client.get(
            "price_rules.json",
            params={"limit": max(1, min(int(limit), 250))},
        )
        rules = result.get("price_rules") or []
        return [r for r in rules if isinstance(r, dict)]

    @staticmethod
    def get_price_rule(
        client: ShopifyAdminClient, rule_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(f"price_rules/{rule_id}.json")
        rule = result.get("price_rule")
        if not isinstance(rule, dict):
            raise ShopifyAdminError(
                f"price_rule {rule_id} not returned",
                path=f"price_rules/{rule_id}.json",
            )
        return rule

    @staticmethod
    def create_price_rule(
        client: ShopifyAdminClient,
        *,
        title: str,
        value_pct: float | None = None,
        value_fixed_usd: float | None = None,
        target_type: str = "line_item",
        target_selection: str = "all",
        allocation_method: str = "across",
        customer_selection: str = "all",
        once_per_customer: bool = False,
        usage_limit: int | None = None,
        starts_at: str | None = None,
        ends_at: str | None = None,
    ) -> dict[str, Any]:
        """Create a price rule. Exactly one of ``value_pct``
        or ``value_fixed_usd`` must be supplied.

        Shopify quirks:
          * Discount values are NEGATIVE (a 10% off rule has
            ``value="-10.0"``, not ``"10.0"``). The helper
            converts for the caller so positive inputs read
            naturally.
          * Percentage values use ``value_type="percentage"``
            + integer-as-string value. Fixed amounts use
            ``value_type="fixed_amount"`` + currency-denominated
            string.
        """
        if value_pct is None and value_fixed_usd is None:
            raise ValueError(
                "exactly one of value_pct / value_fixed_usd "
                "must be supplied",
            )
        if value_pct is not None and value_fixed_usd is not None:
            raise ValueError(
                "only one of value_pct / value_fixed_usd",
            )
        if value_pct is not None:
            value_type = VALUE_TYPE_PERCENTAGE
            value = str(-abs(float(value_pct)))
        else:
            value_type = VALUE_TYPE_FIXED_AMOUNT
            value = str(-abs(float(value_fixed_usd)))

        body: dict[str, Any] = {
            "price_rule": {
                "title": title,
                "target_type": target_type,
                "target_selection": target_selection,
                "allocation_method": allocation_method,
                "value_type": value_type,
                "value": value,
                "customer_selection": customer_selection,
                "once_per_customer": bool(once_per_customer),
                "starts_at": starts_at or _now_iso(),
            }
        }
        if usage_limit is not None:
            body["price_rule"]["usage_limit"] = int(usage_limit)
        if ends_at:
            body["price_rule"]["ends_at"] = ends_at

        result = client.post("price_rules.json", body)
        rule = result.get("price_rule")
        if not isinstance(rule, dict):
            raise ShopifyAdminError(
                "price_rule not returned by create",
                path="price_rules.json",
                body=str(result),
            )
        return rule

    @staticmethod
    def update_price_rule(
        client: ShopifyAdminClient,
        rule_id: int | str,
        *,
        fields: dict[str, Any],
    ) -> dict[str, Any]:
        """Partial update — callers pass only the fields they
        want to change (e.g. ``{"ends_at": "2026-05-01T..."}
        `` to extend an expiry)."""
        if not fields:
            raise ValueError("fields: non-empty dict required")
        result = client.put(
            f"price_rules/{rule_id}.json",
            {"price_rule": dict(fields)},
        )
        rule = result.get("price_rule")
        if not isinstance(rule, dict):
            raise ShopifyAdminError(
                "price_rule not returned by update",
                path=f"price_rules/{rule_id}.json",
            )
        return rule

    @staticmethod
    def delete_price_rule(
        client: ShopifyAdminClient, rule_id: int | str,
    ) -> None:
        """Also deletes every associated discount code —
        Shopify cascades."""
        client.delete(f"price_rules/{rule_id}.json")

    # ── Discount codes ──────────────────────────────────

    @staticmethod
    def list_discount_codes(
        client: ShopifyAdminClient, rule_id: int | str,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"price_rules/{rule_id}/discount_codes.json",
        )
        codes = result.get("discount_codes") or []
        return [c for c in codes if isinstance(c, dict)]

    @staticmethod
    def create_discount_code(
        client: ShopifyAdminClient,
        rule_id: int | str,
        *,
        code: str,
    ) -> dict[str, Any]:
        if not code or not code.strip():
            raise ValueError("code: non-empty required")
        result = client.post(
            f"price_rules/{rule_id}/discount_codes.json",
            {"discount_code": {"code": code.strip().upper()}},
        )
        entry = result.get("discount_code")
        if not isinstance(entry, dict):
            raise ShopifyAdminError(
                "discount_code not returned by create",
                path=(
                    f"price_rules/{rule_id}/"
                    f"discount_codes.json"
                ),
                body=str(result),
            )
        return entry

    @staticmethod
    def delete_discount_code(
        client: ShopifyAdminClient,
        rule_id: int | str,
        code_id: int | str,
    ) -> None:
        client.delete(
            f"price_rules/{rule_id}/"
            f"discount_codes/{code_id}.json",
        )

    @staticmethod
    def lookup_discount_code(
        client: ShopifyAdminClient, code: str,
    ) -> dict[str, Any] | None:
        """Resolve a code string → {rule_id, code_id, ...}.
        Returns None when the code doesn't exist. Used by
        owner-facing "is this code valid?" checks."""
        if not code:
            return None
        try:
            result = client.get(
                "discount_codes/lookup.json",
                params={"code": code.strip()},
            )
        except ShopifyAdminError as exc:
            if exc.status == 404:
                return None
            raise
        return result.get("discount_code") or result or None

    # ── Convenience: one-call percentage code ──────────

    @staticmethod
    def create_percentage_code(
        client: ShopifyAdminClient,
        *,
        code: str,
        value_pct: float,
        title: str | None = None,
        once_per_customer: bool = False,
        usage_limit: int | None = None,
        expires_in_days: int | None = None,
    ) -> dict[str, Any]:
        """Create (price_rule + discount_code) pair in one
        call. Returns ``{"price_rule": {...},
        "discount_code": {...}}`` so callers get both IDs.

        Most common use case — "Make code SUMMER20 = 20% off,
        limited to first 100 orders, expires in 14 days":

            Discounts.create_percentage_code(
                client,
                code="SUMMER20",
                value_pct=20,
                title="Summer 2026 promo",
                usage_limit=100,
                expires_in_days=14,
            )
        """
        ends_at: str | None = None
        if expires_in_days is not None and expires_in_days > 0:
            ends_at = (
                _dt.datetime.now(_dt.timezone.utc)
                + _dt.timedelta(days=int(expires_in_days))
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        rule = Discounts.create_price_rule(
            client,
            title=title or f"Promo: {code}",
            value_pct=value_pct,
            once_per_customer=once_per_customer,
            usage_limit=usage_limit,
            ends_at=ends_at,
        )
        entry = Discounts.create_discount_code(
            client, rule["id"], code=code,
        )
        return {
            "price_rule": rule,
            "discount_code": entry,
        }


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )


# ── Automatic discounts (GraphQL) ─────────────────────────


_AUTO_DISCOUNT_BASIC_CREATE = """
mutation autoDiscount($input: DiscountAutomaticBasicInput!) {
  discountAutomaticBasicCreate(automaticBasicDiscount: $input) {
    automaticDiscountNode { id }
    userErrors { field message }
  }
}
"""


_AUTO_DISCOUNT_BXGY_CREATE = """
mutation bxgyDiscount($input: DiscountAutomaticBxgyInput!) {
  discountAutomaticBxgyCreate(automaticBxgyDiscount: $input) {
    automaticDiscountNode { id }
    userErrors { field message }
  }
}
"""


_AUTO_DISCOUNT_DELETE = """
mutation deleteAutoDiscount($id: ID!) {
  discountAutomaticDelete(id: $id) {
    deletedAutomaticDiscountId
    userErrors { field message }
  }
}
"""


_AUTO_DISCOUNT_LIST = """
query listAutoDiscounts($first: Int!) {
  automaticDiscountNodes(first: $first) {
    edges {
      node {
        id
        automaticDiscount {
          ... on DiscountAutomaticBasic {
            title
            status
            startsAt
            endsAt
          }
          ... on DiscountAutomaticBxgy {
            title
            status
            startsAt
            endsAt
          }
        }
      }
    }
  }
}
"""


def _auto_discount_gid(discount_id: int | str) -> str:
    s = str(discount_id).strip()
    if s.startswith("gid://"):
        return s
    return f"gid://shopify/DiscountAutomaticNode/{s}"


def _auto_user_errors(
    payload: dict[str, Any], mutation: str,
) -> None:
    errors = (payload.get(mutation) or {}).get(
        "userErrors",
    ) or []
    if errors:
        msgs = "; ".join(
            f"{e.get('field')}: {e.get('message')}"
            for e in errors if isinstance(e, dict)
        )
        raise ShopifyAdminError(
            f"{mutation} userErrors: {msgs}",
            path="graphql.json",
            body=str(payload),
        )


class AutomaticDiscounts:
    """GraphQL automatic discounts — applied at checkout
    without a code.

    Two flavours:
      * basic — percentage or fixed-amount off the order
        subtotal. Used for "10% off everything"
        store-wide sales.
      * bxgy — buy-X-get-Y. Used for BOGO, "buy 2 get 1
        free", tiered bundle deals.

    Code-driven discounts still live under ``Discounts``
    above; automatics are fundamentally different because
    they apply without buyer action, so the timing
    controls (startsAt / endsAt) matter more than the
    per-customer usage limit.
    """

    @staticmethod
    def list_discounts(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = client.graphql(
            _AUTO_DISCOUNT_LIST,
            variables={
                "first": max(1, min(int(limit), 250)),
            },
        )
        edges = (
            (result.get("data") or {}).get(
                "automaticDiscountNodes",
            ) or {}
        ).get("edges") or []
        out: list[dict[str, Any]] = []
        for e in edges:
            if not isinstance(e, dict):
                continue
            node = e.get("node")
            if not isinstance(node, dict):
                continue
            ad = node.get("automaticDiscount") or {}
            out.append({
                "id": str(node.get("id") or ""),
                "title": str(ad.get("title") or ""),
                "status": str(ad.get("status") or ""),
                "starts_at": str(ad.get("startsAt") or ""),
                "ends_at": str(ad.get("endsAt") or ""),
            })
        return out

    @staticmethod
    def create_basic_percentage(
        client: ShopifyAdminClient,
        *,
        title: str,
        value_pct: float,
        starts_at: str,
        ends_at: str | None = None,
        combines_with_product: bool = False,
        combines_with_order: bool = False,
        combines_with_shipping: bool = False,
    ) -> str:
        """Order-wide percentage discount applied
        automatically. Returns the GID of the new
        DiscountAutomaticNode.

        Shopify quirk: percentage values on GraphQL are
        expressed as decimals (10% = 0.10), NOT 10.0. The
        helper converts.
        """
        if not title or not starts_at:
            raise ValueError(
                "title + starts_at required",
            )
        if value_pct <= 0 or value_pct > 100:
            raise ValueError(
                "value_pct must be in (0, 100]",
            )
        input_ = {
            "title": title,
            "startsAt": starts_at,
            "customerGets": {
                "value": {
                    "percentage": float(value_pct) / 100.0,
                },
                "items": {"all": True},
            },
            "minimumRequirement": {
                "subtotal": {
                    "greaterThanOrEqualToSubtotal": "0.0",
                },
            },
            "combinesWith": {
                "productDiscounts": bool(
                    combines_with_product,
                ),
                "orderDiscounts": bool(combines_with_order),
                "shippingDiscounts": bool(
                    combines_with_shipping,
                ),
            },
        }
        if ends_at:
            input_["endsAt"] = ends_at
        result = client.graphql(
            _AUTO_DISCOUNT_BASIC_CREATE,
            variables={"input": input_},
        )
        payload = result.get("data") or {}
        _auto_user_errors(
            payload, "discountAutomaticBasicCreate",
        )
        node = (
            payload.get("discountAutomaticBasicCreate")
            or {}
        ).get("automaticDiscountNode") or {}
        node_id = str(node.get("id") or "")
        if not node_id:
            raise ShopifyAdminError(
                "discountAutomaticBasicCreate returned "
                "no id",
                path="graphql.json",
            )
        return node_id

    @staticmethod
    def create_bxgy(
        client: ShopifyAdminClient,
        *,
        title: str,
        customer_buys_qty: int,
        customer_gets_qty: int,
        starts_at: str,
        ends_at: str | None = None,
        uses_per_order_limit: int | None = None,
    ) -> str:
        """Buy-X-get-Y automatic discount. Applies to all
        items by default. Returns the new node's GID."""
        if not title or not starts_at:
            raise ValueError("title + starts_at required")
        if customer_buys_qty < 1 or customer_gets_qty < 1:
            raise ValueError(
                "customer_buys_qty + customer_gets_qty "
                "must be ≥ 1",
            )
        input_: dict[str, Any] = {
            "title": title,
            "startsAt": starts_at,
            "customerBuys": {
                "value": {"quantity": str(customer_buys_qty)},
                "items": {"all": True},
            },
            "customerGets": {
                "value": {
                    "discountOnQuantity": {
                        "quantity": str(customer_gets_qty),
                        "effect": {"percentage": 1.0},
                    },
                },
                "items": {"all": True},
            },
        }
        if ends_at:
            input_["endsAt"] = ends_at
        if uses_per_order_limit is not None:
            input_["usesPerOrderLimit"] = str(
                uses_per_order_limit,
            )
        result = client.graphql(
            _AUTO_DISCOUNT_BXGY_CREATE,
            variables={"input": input_},
        )
        payload = result.get("data") or {}
        _auto_user_errors(
            payload, "discountAutomaticBxgyCreate",
        )
        node = (
            payload.get("discountAutomaticBxgyCreate")
            or {}
        ).get("automaticDiscountNode") or {}
        node_id = str(node.get("id") or "")
        if not node_id:
            raise ShopifyAdminError(
                "discountAutomaticBxgyCreate returned "
                "no id",
                path="graphql.json",
            )
        return node_id

    @staticmethod
    def delete(
        client: ShopifyAdminClient,
        discount_id: int | str,
    ) -> str:
        result = client.graphql(
            _AUTO_DISCOUNT_DELETE,
            variables={
                "id": _auto_discount_gid(discount_id),
            },
        )
        payload = result.get("data") or {}
        _auto_user_errors(
            payload, "discountAutomaticDelete",
        )
        deleted = (
            payload.get("discountAutomaticDelete") or {}
        ).get("deletedAutomaticDiscountId")
        if not deleted:
            raise ShopifyAdminError(
                "discountAutomaticDelete returned no id",
                path="graphql.json",
            )
        return str(deleted)
