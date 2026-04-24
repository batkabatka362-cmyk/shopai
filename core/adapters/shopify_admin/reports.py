"""Shopify analytics + financial reporting surface.

Four thin REST resources bundled together because each one
is small + read-mostly, and engines treat them as one
"business state" pull:

  * ``Reports``       — Shopify Reports API (analytics).
    Read-only surface exposing the per-category rollups
    Shopify computes overnight (sales / finance / customer).
  * ``Payouts``       — Shopify Payments payouts.
    ``payouts.json`` lists amounts deposited to the bank +
    per-balance transaction breakdown.
  * ``Balance``       — real-time Shopify Payments balance.
  * ``TaxRates``      — countries / provinces / shipping
    zones each carry their own tax_rates; this resource
    exposes the authoritative rates the checkout applies.
  * ``Users``         — staff accounts with role + scope.
    Multi-operator stores (owner + VA + fulfillment team)
    read this to surface "who deleted product X?" style
    audit questions.
  * ``Countries`` + ``Provinces`` — read-only geography.
    Feeds tax zone setup + international-shipping quote
    pre-flight.
"""
from __future__ import annotations

import logging
from typing import Any

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)

_logger = logging.getLogger(
    "shopai.shopify_admin.reports",
)


class Reports:
    """Shopify Reports API — read-only analytics rollups."""

    @staticmethod
    def list_reports(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """``category`` filters to Shopify's documented
        buckets: ``sales``, ``finance``, ``customer``,
        ``acquisition``, ``behavior``, ``inventory``,
        ``marketing``, ``orders``, ``profit``."""
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if category:
            params["category"] = str(category)
        result = client.get("reports.json", params=params)
        rows = result.get("reports") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        report_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(f"reports/{report_id}.json")
        report = result.get("report")
        if not isinstance(report, dict):
            raise ShopifyAdminError(
                f"report {report_id} not returned",
                path=f"reports/{report_id}.json",
            )
        return report


class Payouts:
    """Shopify Payments payouts — deposits to the owner's
    bank account."""

    _STATUS = {
        "scheduled", "in_transit", "paid", "failed",
        "canceled",
    }

    @staticmethod
    def list_payouts(
        client: ShopifyAdminClient,
        *,
        status: str | None = None,
        date_min: str | None = None,
        date_max: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if status is not None and status not in Payouts._STATUS:
            raise ValueError(
                f"status must be one of {sorted(Payouts._STATUS)}",
            )
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if status:
            params["status"] = status
        if date_min:
            params["date_min"] = str(date_min)
        if date_max:
            params["date_max"] = str(date_max)
        result = client.get(
            "shopify_payments/payouts.json", params=params,
        )
        rows = result.get("payouts") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        payout_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"shopify_payments/payouts/{payout_id}.json",
        )
        p = result.get("payout")
        if not isinstance(p, dict):
            raise ShopifyAdminError(
                f"payout {payout_id} not returned",
                path=(
                    f"shopify_payments/payouts/{payout_id}.json"
                ),
            )
        return p

    @staticmethod
    def list_transactions(
        client: ShopifyAdminClient,
        *,
        payout_id: int | str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Balance-transaction entries. Optional ``payout_id``
        restricts to one payout's breakdown."""
        params: dict[str, Any] = {
            "limit": max(1, min(int(limit), 250)),
        }
        if payout_id is not None:
            params["payout_id"] = int(payout_id)
        result = client.get(
            "shopify_payments/balance/transactions.json",
            params=params,
        )
        rows = result.get("transactions") or []
        return [r for r in rows if isinstance(r, dict)]


class Balance:
    """Real-time Shopify Payments balance."""

    @staticmethod
    def get(
        client: ShopifyAdminClient,
    ) -> list[dict[str, Any]]:
        """Returns one row per currency Shopify Payments
        holds; each row has ``amount`` + ``currency``."""
        result = client.get(
            "shopify_payments/balance.json",
        )
        rows = result.get("balance") or []
        if isinstance(rows, dict):
            # Single-currency stores sometimes return a dict.
            rows = [rows]
        return [r for r in rows if isinstance(r, dict)]


class TaxRates:
    """Country/province-level tax rates used by checkout."""

    @staticmethod
    def list_countries(
        client: ShopifyAdminClient,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        result = client.get(
            "countries.json",
            params={"limit": max(1, min(int(limit), 250))},
        )
        rows = result.get("countries") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get_country(
        client: ShopifyAdminClient,
        country_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(
            f"countries/{country_id}.json",
        )
        country = result.get("country")
        if not isinstance(country, dict):
            raise ShopifyAdminError(
                f"country {country_id} not returned",
                path=f"countries/{country_id}.json",
            )
        return country

    @staticmethod
    def list_provinces(
        client: ShopifyAdminClient,
        country_id: int | str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        result = client.get(
            f"countries/{country_id}/provinces.json",
            params={"limit": max(1, min(int(limit), 250))},
        )
        rows = result.get("provinces") or []
        return [r for r in rows if isinstance(r, dict)]


class Users:
    """Staff account introspection — read-only (staff
    management lives in Shopify's dashboard)."""

    @staticmethod
    def list_users(
        client: ShopifyAdminClient,
    ) -> list[dict[str, Any]]:
        result = client.get("users.json")
        rows = result.get("users") or []
        return [r for r in rows if isinstance(r, dict)]

    @staticmethod
    def get(
        client: ShopifyAdminClient,
        user_id: int | str,
    ) -> dict[str, Any]:
        result = client.get(f"users/{user_id}.json")
        user = result.get("user")
        if not isinstance(user, dict):
            raise ShopifyAdminError(
                f"user {user_id} not returned",
                path=f"users/{user_id}.json",
            )
        return user

    @staticmethod
    def current(
        client: ShopifyAdminClient,
    ) -> dict[str, Any]:
        """The user associated with the current API token —
        useful for audit-log ``actor`` fields."""
        result = client.get("users/current.json")
        user = result.get("user")
        if not isinstance(user, dict):
            raise ShopifyAdminError(
                "current user not returned",
                path="users/current.json",
            )
        return user
