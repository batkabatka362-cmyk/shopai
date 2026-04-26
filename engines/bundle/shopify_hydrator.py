"""Bundle Engine — Shopify catalog hydrator.

Thin per-engine wrapper around ``engines._shopify_hydrator.hydrate``.
Auto-fetches products + orders when the caller leaves them empty;
pass-through otherwise. See the shared module for the full contract.
"""
from __future__ import annotations

from typing import Any

from engines._shopify_hydrator import hydrate


def hydrate_products(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else fetch via SHOPIFY_LIST_PRODUCTS."""
    return hydrate(
        supplied=supplied,
        capability_name="SHOPIFY_LIST_PRODUCTS",
        list_field="products",
        limit=limit,
        query=query,
    )


def hydrate_orders(
    supplied: list[dict[str, Any]] | None,
    *,
    limit: int | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Pass-through if supplied; else fetch via SHOPIFY_FETCH_ORDERS.

    Orders are OPTIONAL for the bundle engine — affinity analyser
    tolerates an empty list — so failure here is silent.
    """
    return hydrate(
        supplied=supplied,
        capability_name="SHOPIFY_FETCH_ORDERS",
        list_field="orders",
        limit=limit,
        query=query,
    )
