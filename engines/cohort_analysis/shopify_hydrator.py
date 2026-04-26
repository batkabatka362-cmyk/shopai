"""Cohort Analysis Engine — Shopify customer + order hydrator.

Thin per-engine wrappers around ``engines._shopify_hydrator.hydrate``.
Cohort analysis needs BOTH customers (cohort assignment by signup
date) and orders (retention math). Either can be hydrated
independently — the engine runs as long as one is non-empty.
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


def hydrate_orders(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else fetch via SHOPIFY_FETCH_ORDERS."""
    return hydrate(
        supplied=supplied,
        capability_name="SHOPIFY_FETCH_ORDERS",
        list_field="orders",
        limit=limit,
        query=query,
    )
