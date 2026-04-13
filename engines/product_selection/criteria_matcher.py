"""Product Selection Engine — criteria matcher.

Matches candidate products against selection criteria such as minimum
margin, price range, and other configurable thresholds.
"""
from __future__ import annotations

import copy
from typing import Any


def match_criteria(
    candidates: list[dict[str, Any]],
    criteria: dict[str, Any],
) -> dict[str, Any]:
    """Match candidates against selection criteria.

    Args:
        candidates: List of candidate product dicts.
        criteria: Selection criteria dict.

    Returns:
        Structured dict with matched candidates.
    """
    try:
        items = copy.deepcopy(candidates)
        min_margin = float(criteria.get("min_margin", 0.1))
        min_price = float(criteria.get("min_price", 0.0))
        max_price = float(criteria.get("max_price", float("inf")))

        matched: list[dict[str, Any]] = []
        for item in items:
            margin = float(item.get("margin", 0.0))
            price = float(item.get("price", 0.0))

            passes = True
            reasons: list[str] = []
            if margin < min_margin:
                passes = False
                reasons.append(f"margin {margin:.2%} < {min_margin:.2%}")
            if price < min_price:
                passes = False
                reasons.append(f"price {price} < {min_price}")
            if price > max_price:
                passes = False
                reasons.append(f"price {price} > {max_price}")

            item["criteria_pass"] = passes
            item["criteria_reasons"] = reasons
            matched.append(item)

        return {
            "status": "success",
            "matched": matched,
            "pass_count": sum(1 for m in matched if m["criteria_pass"]),
        }
    except Exception as exc:
        return {
            "status": "error",
            "matched": [],
            "error": f"Criteria matching failed: {exc}",
        }
