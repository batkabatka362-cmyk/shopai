"""Monetization Engine — upsell mapper.

Maps upsell opportunities: premium alternatives, add-ons,
extended warranties, and volume upgrades.
"""
from __future__ import annotations

import copy
from typing import Any


def map_upsells(
    products: list[dict[str, Any]],
    revenue_data: dict[str, Any],
) -> dict[str, Any]:
    """Map upsell opportunities across the catalog.

    Args:
        products: Product catalog with pricing tiers.
        revenue_data: Revenue metrics.

    Returns:
        Structured dict with upsell mappings.
    """
    try:
        prods = copy.deepcopy(products)
        upsells: list[dict[str, Any]] = []

        # Group products by category for premium upgrades
        by_category: dict[str, list[dict[str, Any]]] = {}
        for prod in prods:
            cat = str(prod.get("category", "uncategorized"))
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(prod)

        for cat, cat_prods in by_category.items():
            if len(cat_prods) < 2:
                continue

            sorted_prods = sorted(cat_prods, key=lambda p: float(p.get("price", 0)))

            for i, prod in enumerate(sorted_prods[:-1]):
                premium = sorted_prods[i + 1]
                base_price = float(prod.get("price", 0))
                premium_price = float(premium.get("price", 0))

                if base_price > 0 and premium_price > base_price:
                    uplift = round(premium_price - base_price, 2)
                    uplift_pct = round((uplift / base_price) * 100, 1)

                    if 10 <= uplift_pct <= 100:
                        upsells.append({
                            "type": "premium_upgrade",
                            "base_product": str(prod.get("id", "")),
                            "upsell_product": str(premium.get("id", "")),
                            "price_uplift": uplift,
                            "uplift_pct": uplift_pct,
                            "category": cat,
                        })

        total_potential = sum(u.get("price_uplift", 0) for u in upsells)

        return {
            "status": "success",
            "upsells": upsells,
            "total_upsells": len(upsells),
            "total_potential_uplift": round(total_potential, 2),
        }
    except Exception as exc:
        return {
            "status": "error",
            "upsells": [],
            "error": f"Upsell mapping failed: {exc}",
        }
