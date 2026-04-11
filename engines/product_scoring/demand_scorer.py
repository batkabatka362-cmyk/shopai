"""Product Scoring Engine — demand scorer.

Scores products based on sales velocity and demand indicators.
Higher daily sales = higher demand score.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def score_demand(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score each product on demand strength.

    Args:
        products: List of product dicts with daily_sales_avg.

    Returns:
        Structured dict with per-product demand scores.
    """
    try:
        items = copy.deepcopy(products)
        scores: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            daily_avg = float(item.get("daily_sales_avg", 0.0))

            # Score 0-10 based on daily velocity
            if daily_avg >= 50.0:
                score = 10.0
                tier = "exceptional"
            elif daily_avg >= 20.0:
                score = 8.0 + (daily_avg - 20.0) / 15.0
                tier = "high"
            elif daily_avg >= 5.0:
                score = 5.0 + (daily_avg - 5.0) / 5.0
                tier = "moderate"
            elif daily_avg >= 1.0:
                score = 2.0 + (daily_avg - 1.0) * 0.75
                tier = "low"
            else:
                score = daily_avg * 2.0
                tier = "minimal"

            score = round(min(10.0, max(0.0, score)), 2)

            scores.append({
                "id": product_id,
                "score": score,
                "daily_velocity": daily_avg,
                "demand_tier": tier,
            })

        return {"status": "success", "scores": scores}
    except Exception as exc:
        return {"status": "error", "scores": [], "error": f"Demand scoring failed: {exc}"}
