"""Product Filter Engine — brand filter.

Filters products that don't fit the store's brand profile or are on the
brand blocklist. Computes a brand-fit score (0-100).

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_MIN_FIT_SCORE = 40  # Products below this score are rejected


def filter_by_brand(
    products: list[dict[str, Any]],
    blocked_brands: list[str] | None = None,
    brand_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Filter products by brand fit.

    Args:
        products: List of ProductCandidate dicts.
        blocked_brands: List of brand names to block.
        brand_profile: Store brand profile for fit scoring.

    Returns:
        Structured dict with passed and rejected lists.
    """
    try:
        items = copy.deepcopy(products)
        passed: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        fit_scores: dict[str, float] = {}

        blocked_set = {b.lower().strip() for b in (blocked_brands or [])}
        profile = brand_profile or {}
        target_tier = str(profile.get("price_tier", "mid")).lower()
        target_categories = {
            c.lower().strip()
            for c in profile.get("preferred_categories", [])
        }

        for item in items:
            product_id = str(item.get("id", "unknown"))
            brand = str(item.get("brand", "")).lower().strip()
            category = str(item.get("category", "")).lower().strip()
            price = float(item.get("sale_price", 0.0))

            # Blocked brand check
            if brand in blocked_set:
                item["rejection_stage"] = "brand_filter"
                item["rejection_reason"] = f"Brand '{brand}' is blocked"
                rejected.append(item)
                fit_scores[product_id] = 0.0
                continue

            # Compute fit score
            score = 50.0  # base

            # Category alignment bonus
            if target_categories and category in target_categories:
                score += 25.0
            elif target_categories:
                score -= 10.0

            # Price tier alignment
            if target_tier == "premium" and price >= 50.0:
                score += 15.0
            elif target_tier == "budget" and price <= 20.0:
                score += 15.0
            elif target_tier == "mid" and 15.0 <= price <= 80.0:
                score += 10.0

            score = max(0.0, min(100.0, score))
            fit_scores[product_id] = round(score, 1)

            if score >= _MIN_FIT_SCORE:
                item["brand_fit_score"] = round(score, 1)
                passed.append(item)
            else:
                item["rejection_stage"] = "brand_filter"
                item["rejection_reason"] = (
                    f"Brand fit score {score:.1f} below minimum {_MIN_FIT_SCORE}"
                )
                rejected.append(item)

        return {
            "status": "success",
            "passed": passed,
            "rejected": rejected,
            "fit_scores": fit_scores,
        }
    except Exception as exc:
        return {
            "status": "error",
            "passed": [],
            "rejected": [],
            "error": f"Brand filter failed: {exc}",
        }
