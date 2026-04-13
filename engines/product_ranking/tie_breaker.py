"""Product Ranking Engine — tie breaker.

Resolves tied ranks using secondary criteria: margin > demand > id.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def break_ties(
    ranked_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Break ties among products with identical final scores.

    Args:
        ranked_products: Ranked product list (may have ties).

    Returns:
        Structured dict with tie-resolved rankings.
    """
    try:
        items = copy.deepcopy(ranked_products)

        # Re-sort with tie-breaking: final_score desc, margin desc, demand desc, id asc
        items.sort(
            key=lambda x: (
                -x.get("final_score", 0.0),
                -float(x.get("margin_score", 0.0)),
                -float(x.get("demand_score", 0.0)),
                str(x.get("id", "")),
            )
        )

        for idx, item in enumerate(items, 1):
            item["rank"] = idx

        return {"status": "success", "ranked_products": items}
    except Exception as exc:
        return {"status": "error", "ranked_products": [], "error": f"Tie breaking failed: {exc}"}
