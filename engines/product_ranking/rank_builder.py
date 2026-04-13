"""Product Ranking Engine — rank builder.

Sorts products by final score and assigns rank numbers.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_ranks(
    weighted_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Sort products by final score and assign ranks.

    Args:
        weighted_products: Products with final_score computed.

    Returns:
        Structured dict with ranked products.
    """
    try:
        items = copy.deepcopy(weighted_products)
        items.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)

        for idx, item in enumerate(items, 1):
            item["rank"] = idx

        return {"status": "success", "ranked_products": items}
    except Exception as exc:
        return {"status": "error", "ranked_products": [], "error": f"Rank building failed: {exc}"}
