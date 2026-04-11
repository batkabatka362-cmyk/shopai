"""Trend Discovery Engine — marketplace scanner.

Scan marketplace data for emerging products and categories.
"""
from __future__ import annotations

import copy
from typing import Any


def scan_marketplace(
    **kwargs: Any,
) -> dict[str, Any]:
    """Scan marketplace for emerging products.

    Args:
        **kwargs: Must include 'marketplace_data' dict.

    Returns:
        Structured dict with marketplace scan results.
    """
    try:
        marketplace_data = copy.deepcopy(kwargs.get("marketplace_data", {}))
        products = marketplace_data.get("trending_products", [])
        new_categories = marketplace_data.get("new_categories", [])

        hot_products: list[dict[str, Any]] = []

        for prod in products:
            name = str(prod.get("name", ""))
            sales_rank_change = int(prod.get("rank_change", 0))
            review_velocity = float(prod.get("review_velocity", 0))
            days_on_market = int(prod.get("days_on_market", 365))

            # Hot score based on rank improvement and review velocity
            hot_score = 0.0
            if sales_rank_change < -100:  # Big rank improvement (lower = better)
                hot_score += 0.5
            elif sales_rank_change < -10:
                hot_score += 0.3
            if review_velocity > 10:
                hot_score += 0.3
            elif review_velocity > 3:
                hot_score += 0.15
            if days_on_market < 30:
                hot_score += 0.2

            hot_products.append({
                "name": name,
                "hot_score": round(min(hot_score, 1.0), 2),
                "rank_change": sales_rank_change,
                "review_velocity": review_velocity,
                "days_on_market": days_on_market,
            })

        hot_products.sort(key=lambda p: p["hot_score"], reverse=True)

        emerging_niches: list[dict[str, Any]] = [
            {"name": cat.get("name", ""), "growth": cat.get("growth_pct", 0)}
            for cat in new_categories
        ]

        return {
            "status": "success",
            "result": {
                "hot_products": hot_products[:20],
                "emerging_niches": emerging_niches,
            },
        }
    except Exception as exc:
        return {"status": "error", "error": f"Marketplace scanning failed: {exc}"}
