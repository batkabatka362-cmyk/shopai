"""Wishlist Engine — wishlist analyzer.

Analyzes wishlist patterns: popular products, wishlist sizes,
conversion potential, and abandonment signals.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_wishlists(
    wishlists: list[dict[str, Any]],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze wishlist patterns.

    Args:
        wishlists: Wishlist records.
        products: Product records.

    Returns:
        Structured dict with wishlist analysis.
    """
    try:
        wl_data = copy.deepcopy(wishlists)

        total_wishlists = len(wl_data)
        total_items = 0
        product_frequency: dict[str, int] = {}

        for wl in wl_data:
            items = wl.get("items", wl.get("product_ids", []))
            total_items += len(items)
            for item in items:
                pid = str(item.get("product_id", item) if isinstance(item, dict) else item)
                product_frequency[pid] = product_frequency.get(pid, 0) + 1

        avg_size = round(total_items / total_wishlists, 1) if total_wishlists > 0 else 0.0

        # Most wishlisted products
        top_products = sorted(
            product_frequency.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:20]

        # Build product lookup
        prod_map = {str(p.get("id", "")): p for p in products}

        top_wishlisted: list[dict[str, Any]] = []
        for pid, count in top_products:
            prod = prod_map.get(pid, {})
            top_wishlisted.append({
                "product_id": pid,
                "title": str(prod.get("title", "")),
                "wishlist_count": count,
                "price": float(prod.get("price", 0)),
            })

        return {
            "status": "success",
            "analysis": {
                "total_wishlists": total_wishlists,
                "total_items": total_items,
                "avg_wishlist_size": avg_size,
                "unique_products_wishlisted": len(product_frequency),
                "top_wishlisted": top_wishlisted,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": f"Wishlist analysis failed: {exc}",
        }
