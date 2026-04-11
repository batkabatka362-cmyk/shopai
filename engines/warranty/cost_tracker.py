"""Warranty Engine — cost tracker.

Tracks warranty costs: total claim costs, cost per product,
cost trends, and cost as percentage of revenue.
"""
from __future__ import annotations

import copy
from typing import Any


def track_costs(
    claims_processed: dict[str, Any],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Track warranty costs.

    Args:
        claims_processed: Processed claims data.
        products: Product records.

    Returns:
        Structured dict with cost tracking.
    """
    try:
        details = claims_processed.get("details", [])

        total_cost = sum(float(c.get("cost", 0)) for c in details)
        total_claims = len(details)
        avg_cost = round(total_cost / total_claims, 2) if total_claims > 0 else 0.0

        # Cost by product
        cost_by_product: dict[str, float] = {}
        claims_by_product: dict[str, int] = {}

        for claim in details:
            pid = claim.get("product_id", "unknown")
            cost = float(claim.get("cost", 0))
            cost_by_product[pid] = cost_by_product.get(pid, 0) + cost
            claims_by_product[pid] = claims_by_product.get(pid, 0) + 1

        # Cost by category
        cost_by_category: dict[str, float] = {}
        for claim in details:
            cat = claim.get("category", "other")
            cost = float(claim.get("cost", 0))
            cost_by_category[cat] = cost_by_category.get(cat, 0) + cost

        # Estimate warranty cost as % of revenue
        total_revenue = sum(
            float(p.get("price", 0)) * float(p.get("quantity_sold", 0))
            for p in products
        )
        warranty_pct = round(total_cost / total_revenue * 100, 2) if total_revenue > 0 else 0.0

        return {
            "status": "success",
            "costs": {
                "total_warranty_cost": round(total_cost, 2),
                "avg_cost_per_claim": avg_cost,
                "warranty_cost_pct_of_revenue": warranty_pct,
                "cost_by_product": {k: round(v, 2) for k, v in cost_by_product.items()},
                "cost_by_category": {k: round(v, 2) for k, v in cost_by_category.items()},
                "highest_cost_product": max(cost_by_product.items(), key=lambda x: x[1])[0] if cost_by_product else None,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "costs": {},
            "error": f"Cost tracking failed: {exc}",
        }
