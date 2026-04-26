"""Churn Prediction Engine — Shopify customer hydrator.

Thin per-engine wrapper around ``engines._shopify_hydrator.hydrate``.
Auto-fetches customers via Capability.SHOPIFY_FETCH_CUSTOMERS when
the caller leaves them empty; pass-through otherwise.

Optional ``query`` filter scopes the auto-fetch (e.g.
``"orders_count:>0 AND last_order_date:<2026-01-01"``) so callers
can run churn analysis on a specific cohort without pre-fetching.
"""
from __future__ import annotations

from typing import Any

from engines._shopify_hydrator import hydrate


def hydrate_customers(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else fetch via SHOPIFY_FETCH_CUSTOMERS."""
    return hydrate(
        supplied=supplied,
        capability_name="SHOPIFY_FETCH_CUSTOMERS",
        list_field="customers",
        limit=limit,
        query=query,
    )
