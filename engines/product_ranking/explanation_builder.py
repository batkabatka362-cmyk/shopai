"""Product Ranking Engine — explanation builder.

Generates human-readable explanations for each product's ranking.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_explanations(
    ranked_products: list[dict[str, Any]],
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add ranking explanations to each product.

    Args:
        ranked_products: Final ranked product list.
        criteria: Criteria used for weighting.

    Returns:
        Structured dict with explained rankings.
    """
    try:
        items = copy.deepcopy(ranked_products)
        total = len(items)

        for item in items:
            rank = item.get("rank", 0)
            title = str(item.get("title", "Unknown"))
            score = item.get("final_score", 0.0)
            weighted = item.get("weighted_scores", {})

            # Find strongest dimension
            strongest = max(weighted, key=weighted.get) if weighted else "demand"
            strongest_val = weighted.get(strongest, 0.0)

            percentile = round((1.0 - (rank - 1) / max(total, 1)) * 100, 0)

            explanation = (
                f"Ranked #{rank} of {total} (top {percentile:.0f}%). "
                f"Final score {score:.2f}. "
                f"Strongest dimension: {strongest} ({strongest_val:.3f}). "
            )

            risk = str(item.get("risk_level", "low"))
            if risk in ("high", "critical"):
                explanation += f"Note: {risk} risk level applied a penalty."

            item["explanation"] = explanation

        return {"status": "success", "ranked_products": items}
    except Exception as exc:
        return {"status": "error", "ranked_products": [], "error": f"Explanation building failed: {exc}"}
