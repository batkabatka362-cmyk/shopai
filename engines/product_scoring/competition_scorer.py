"""Product Scoring Engine — competition scorer.

Scores products based on competitive landscape.
Fewer competitors = higher score (less saturated market).

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def score_competition(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score each product on competition level.

    Args:
        products: List of product dicts.

    Returns:
        Structured dict with per-product competition scores.
    """
    try:
        items = copy.deepcopy(products)
        scores: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            competitors = int(item.get("competitor_count", 5))

            # Inverse scoring: fewer competitors = higher score
            if competitors <= 2:
                score = 9.5
                level = "low"
            elif competitors <= 5:
                score = 8.0 - (competitors - 2) * 0.5
                level = "moderate"
            elif competitors <= 15:
                score = 6.5 - (competitors - 5) * 0.3
                level = "high"
            elif competitors <= 30:
                score = 3.5 - (competitors - 15) * 0.15
                level = "very_high"
            else:
                score = max(0.5, 1.5 - (competitors - 30) * 0.03)
                level = "saturated"

            score = round(min(10.0, max(0.0, score)), 2)

            scores.append({
                "id": product_id,
                "score": score,
                "competitor_count": competitors,
                "competition_level": level,
            })

        return {"status": "success", "scores": scores}
    except Exception as exc:
        return {"status": "error", "scores": [], "error": f"Competition scoring failed: {exc}"}
