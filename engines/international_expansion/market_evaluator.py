"""International Expansion Engine — market evaluator.

Evaluates target markets by GDP, ecommerce penetration, and ease of entry.
All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Market reference data (simplified benchmarks)
# ---------------------------------------------------------------------------

_MARKET_DATA: dict[str, dict[str, float]] = {
    "US": {"gdp_trillion": 25.5, "ecommerce_pct": 15.0, "ease_score": 0.9},
    "UK": {"gdp_trillion": 3.1, "ecommerce_pct": 27.0, "ease_score": 0.85},
    "DE": {"gdp_trillion": 4.1, "ecommerce_pct": 18.0, "ease_score": 0.8},
    "FR": {"gdp_trillion": 2.8, "ecommerce_pct": 14.0, "ease_score": 0.75},
    "JP": {"gdp_trillion": 4.2, "ecommerce_pct": 12.0, "ease_score": 0.7},
    "AU": {"gdp_trillion": 1.7, "ecommerce_pct": 16.0, "ease_score": 0.88},
    "CA": {"gdp_trillion": 2.1, "ecommerce_pct": 13.0, "ease_score": 0.87},
    "BR": {"gdp_trillion": 1.9, "ecommerce_pct": 9.0, "ease_score": 0.5},
    "IN": {"gdp_trillion": 3.7, "ecommerce_pct": 7.0, "ease_score": 0.45},
    "KR": {"gdp_trillion": 1.7, "ecommerce_pct": 29.0, "ease_score": 0.72},
    "MX": {"gdp_trillion": 1.3, "ecommerce_pct": 6.0, "ease_score": 0.55},
    "CN": {"gdp_trillion": 17.9, "ecommerce_pct": 25.0, "ease_score": 0.35},
}

_DEFAULT_MARKET = {"gdp_trillion": 1.0, "ecommerce_pct": 8.0, "ease_score": 0.5}


def evaluate_markets(
    target_markets: list[str],
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate target markets by GDP, ecommerce penetration, ease of entry.

    Args:
        target_markets: List of market codes (e.g. ["UK", "DE", "JP"]).
        products: Product list for context.

    Returns:
        Structured dict with market scores.
    """
    try:
        markets = copy.deepcopy(target_markets)
        scores: list[dict[str, Any]] = []

        for market_code in markets:
            code = market_code.upper().strip()
            ref = _MARKET_DATA.get(code, _DEFAULT_MARKET)

            gdp_score = round(min(ref["gdp_trillion"] / 25.5, 1.0), 3)
            ecom_score = round(min(ref["ecommerce_pct"] / 30.0, 1.0), 3)
            ease = ref["ease_score"]

            overall = round(
                gdp_score * 0.3 + ecom_score * 0.4 + ease * 0.3, 3
            )

            if overall >= 0.7:
                rec = "strongly_recommended"
            elif overall >= 0.5:
                rec = "recommended"
            elif overall >= 0.3:
                rec = "consider"
            else:
                rec = "not_recommended"

            scores.append({
                "market": code,
                "gdp_score": gdp_score,
                "ecommerce_penetration_score": ecom_score,
                "ease_of_entry_score": ease,
                "overall_score": overall,
                "recommendation": rec,
            })

        scores.sort(key=lambda s: s["overall_score"], reverse=True)

        return {
            "status": "success",
            "market_scores": scores,
        }
    except Exception as exc:
        return {
            "status": "error",
            "market_scores": [],
            "error": f"Market evaluation failed: {exc}",
        }
