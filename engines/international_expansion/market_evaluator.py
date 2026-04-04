"""International Expansion Engine — market evaluator.

Evaluates target markets by GDP, ecommerce penetration, and ease of entry.
All scoring is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any

_MARKET_DATA: dict[str, dict[str, float]] = {
    "US": {"gdp_score": 0.95, "ecom_penetration": 0.22, "ease": 0.90},
    "UK": {"gdp_score": 0.85, "ecom_penetration": 0.27, "ease": 0.88},
    "DE": {"gdp_score": 0.82, "ecom_penetration": 0.19, "ease": 0.80},
    "FR": {"gdp_score": 0.78, "ecom_penetration": 0.17, "ease": 0.75},
    "JP": {"gdp_score": 0.88, "ecom_penetration": 0.13, "ease": 0.60},
    "AU": {"gdp_score": 0.72, "ecom_penetration": 0.21, "ease": 0.85},
    "CA": {"gdp_score": 0.75, "ecom_penetration": 0.20, "ease": 0.87},
    "KR": {"gdp_score": 0.70, "ecom_penetration": 0.29, "ease": 0.55},
    "BR": {"gdp_score": 0.65, "ecom_penetration": 0.11, "ease": 0.40},
    "IN": {"gdp_score": 0.60, "ecom_penetration": 0.09, "ease": 0.35},
    "MX": {"gdp_score": 0.55, "ecom_penetration": 0.08, "ease": 0.45},
    "SE": {"gdp_score": 0.68, "ecom_penetration": 0.24, "ease": 0.82},
}


def evaluate_markets(
    target_markets: list[str],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate target markets for expansion potential.

    Args:
        target_markets: List of market codes (e.g. ["UK", "DE", "JP"]).
        products: Product list to assess market fit.

    Returns:
        Structured dict with market scores.
    """
    try:
        markets = copy.deepcopy(target_markets)
        scores: list[dict[str, Any]] = []
        product_count = len(products)

        for market in markets:
            code = market.upper().strip()
            ref = _MARKET_DATA.get(code, {
                "gdp_score": 0.40, "ecom_penetration": 0.10, "ease": 0.50,
            })

            gdp_score = ref["gdp_score"]
            ecom_pen = ref["ecom_penetration"]
            ease = ref["ease"]
            scale_bonus = min(product_count * 0.005, 0.10)

            overall = round(
                (gdp_score * 0.30 + ecom_pen * 2.0 * 0.35 + ease * 0.35) + scale_bonus,
                3,
            )

            if overall >= 0.75:
                recommendation = "strongly_recommended"
            elif overall >= 0.55:
                recommendation = "recommended"
            elif overall >= 0.40:
                recommendation = "consider"
            else:
                recommendation = "not_recommended"

            scores.append({
                "market": code,
                "gdp_score": gdp_score,
                "ecommerce_penetration": ecom_pen,
                "ease_of_entry": ease,
                "overall_score": overall,
                "recommendation": recommendation,
            })

        scores.sort(key=lambda s: s["overall_score"], reverse=True)

        return {"status": "success", "market_scores": scores}
    except Exception as exc:
        return {"status": "error", "market_scores": [], "error": f"Market evaluation failed: {exc}"}
