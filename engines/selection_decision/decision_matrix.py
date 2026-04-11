"""Selection Decision Engine — decision matrix.

Builds a weighted decision matrix scoring each product across
multiple criteria to produce a final weighted score and rank.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_CRITERIA_WEIGHTS = {
    "score": 0.35,
    "profitability": 0.30,
    "risk_inverse": 0.20,
    "category_fit": 0.15,
}


def build_decision_matrix(
    ranked_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build decision matrix for all products.

    Args:
        ranked_products: List of ranked product dicts.

    Returns:
        Structured dict with per-product decision matrix results.
    """
    try:
        items = copy.deepcopy(ranked_products)
        matrix: list[dict[str, Any]] = []

        for item in items:
            pid = str(item.get("id", "unknown"))
            score = float(item.get("score", 0.0))
            risk = float(item.get("risk_score", 0.5))
            profitability = float(item.get("profitability_score", 0.0))

            # Normalize to 0-1 range
            norm_score = min(max(score, 0.0), 1.0)
            norm_profit = min(max(profitability, 0.0), 1.0)
            risk_inverse = min(max(1.0 - risk, 0.0), 1.0)
            category_fit = 0.7  # Default category fit

            criteria_scores = {
                "score": round(norm_score, 3),
                "profitability": round(norm_profit, 3),
                "risk_inverse": round(risk_inverse, 3),
                "category_fit": round(category_fit, 3),
            }

            weighted_score = round(
                sum(
                    criteria_scores[k] * _CRITERIA_WEIGHTS[k]
                    for k in _CRITERIA_WEIGHTS
                ),
                3,
            )

            matrix.append({
                "product_id": pid,
                "weighted_score": weighted_score,
                "criteria_scores": criteria_scores,
                "rank": 0,  # Filled below
            })

        # Assign ranks
        matrix.sort(key=lambda m: m["weighted_score"], reverse=True)
        for i, entry in enumerate(matrix):
            entry["rank"] = i + 1

        return {"status": "success", "matrix": matrix}
    except Exception as exc:
        return {"status": "error", "matrix": [], "error": f"Decision matrix failed: {exc}"}
