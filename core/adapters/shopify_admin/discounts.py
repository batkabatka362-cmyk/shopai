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
