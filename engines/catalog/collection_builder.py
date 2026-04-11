"""Catalog Engine — collection builder.

Builds smart collections from products based on shared
attributes: price range, season, popularity, newness.
"""
from __future__ import annotations

import copy
from typing import Any


def build_collections(
    products: list[dict[str, Any]],
    categories: dict[str, Any],
) -> dict[str, Any]:
    """Build product collections.

    Args:
        products: Product records.
        categories: Organized categories.

    Returns:
        Structured dict with built collections.
    """
    try:
        prods = copy.deepcopy(products)
        collections: list[dict[str, Any]] = []

        if not prods:
            return {"status": "success", "collections": [], "total_collections": 0}

        # Price-based collections
        prices = [float(p.get("price", 0)) for p in prods if p.get("price")]
        if prices:
            avg_price = sum(prices) / len(prices)
            budget = [p for p in prods if float(p.get("price", 0)) < avg_price * 0.5]
            premium = [p for p in prods if float(p.get("price", 0)) > avg_price * 1.5]

            if budget:
                collections.append({
                    "name": "Budget Picks",
                    "type": "price_based",
                    "products": [str(p.get("id", "")) for p in budget],
                    "count": len(budget),
                })
            if premium:
                collections.append({
                    "name": "Premium Selection",
                    "type": "price_based",
                    "products": [str(p.get("id", "")) for p in premium],
                    "count": len(premium),
                })

        # Best sellers collection
        best = [p for p in prods if float(p.get("quantity_sold", 0)) > 0]
        best.sort(key=lambda p: float(p.get("quantity_sold", 0)), reverse=True)
        top_sellers = best[:min(20, len(best))]
        if top_sellers:
            collections.append({
                "name": "Best Sellers",
                "type": "popularity",
                "products": [str(p.get("id", "")) for p in top_sellers],
                "count": len(top_sellers),
            })

        # New arrivals
        new = [p for p in prods if p.get("is_new", False)]
        if new:
            collections.append({
                "name": "New Arrivals",
                "type": "recency",
                "products": [str(p.get("id", "")) for p in new],
                "count": len(new),
            })

        return {
            "status": "success",
            "collections": collections,
            "total_collections": len(collections),
        }
    except Exception as exc:
        return {
            "status": "error",
            "collections": [],
            "error": f"Collection building failed: {exc}",
        }
