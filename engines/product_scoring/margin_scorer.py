"""Product Scoring Engine — margin scorer.

Scores products based on profit margin percentage.
Higher margins = higher scores.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def score_margins(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score each product on margin strength.

    Args:
        products: List of product dicts.

    Returns:
        Structured dict with per-product margin scores.
    """
    try:
        items = copy.deepcopy(products)
        scores: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            sale_price = float(item.get("sale_price", 0.0))
            unit_cost = float(item.get("unit_cost", 0.0))

            margin_pct = 0.0
            if sale_price > 0:
                margin_pct = round(((sale_price - unit_cost) / sale_price) * 100.0, 2)

            # Score 0-10 based on margin
            if margin_pct >= 60.0:
                score = 10.0
                tier = "exceptional"
            elif margin_pct >= 40.0:
                score = 7.0 + (margin_pct - 40.0) / 6.67
                tier = "high"
            elif margin_pct >= 20.0:
                score = 4.0 + (margin_pct - 20.0) / 6.67
                tier = "moderate"
            elif margin_pct >= 10.0:
                score = 2.0 + (margin_pct - 10.0) / 5.0
                tier = "low"
            else:
                score = margin_pct / 5.0
                tier = "minimal"

            score = round(min(10.0, max(0.0, score)), 2)

            scores.append({
                "id": product_id,
                "score": score,
                "margin_pct": margin_pct,
                "margin_tier": tier,
            })

        return {"status": "success", "scores": scores}
    except Exception as exc:
        return {"status": "error", "scores": [], "error": f"Margin scoring failed: {exc}"}
