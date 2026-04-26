"""Catalog Engine — Shopify product hydrator.

Thin per-engine wrapper around ``engines._shopify_hydrator.hydrate``.
Auto-fetches products via Capability.SHOPIFY_LIST_PRODUCTS when
the caller leaves them empty.
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
