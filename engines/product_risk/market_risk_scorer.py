"""Product Risk Engine — market risk scorer.

Assesses market and demand risk per product: demand volatility,
competition intensity, and market trend analysis.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_HIGH_VOLATILITY_THRESHOLD = 0.7
_COMPETITION_LEVELS = {"low": 0.15, "medium": 0.40, "high": 0.70, "extreme": 0.90}
_DEMAND_TRENDS = {"growing": 0.10, "stable": 0.30, "declining": 0.65, "volatile": 0.80}


def score_market_risk(
    products: list[dict[str, Any]],
    market_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score market risk for each product.

    Args:
        products: List of product dicts.
        market_data: List of market context dicts.

    Returns:
        Structured dict with per-product market risk scores.
    """
    try:
        items = copy.deepcopy(products)
        mkt_map: dict[str, dict[str, Any]] = {}
        for m in market_data:
            cat = str(m.get("category", ""))
            if cat:
                mkt_map[cat] = m

        scores: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            category = str(item.get("category", ""))
            mkt = mkt_map.get(category, {})

            demand_trend = str(mkt.get("demand_trend", "stable"))
            competition = str(mkt.get("competition_level", "medium"))
            volatility = float(mkt.get("market_volatility", 0.5))

            demand_risk = _DEMAND_TRENDS.get(demand_trend, 0.30)
            competition_risk = _COMPETITION_LEVELS.get(competition, 0.40)
            volatility_risk = min(volatility, 1.0)

            market_risk_score = round(
                demand_risk * 0.35 + competition_risk * 0.35 + volatility_risk * 0.30,
                3,
            )

            if market_risk_score < 0.25:
                risk_level = "low"
            elif market_risk_score < 0.50:
                risk_level = "moderate"
            elif market_risk_score < 0.75:
                risk_level = "high"
            else:
                risk_level = "critical"

            scores.append({
                "product_id": product_id,
                "demand_risk": round(demand_risk, 3),
                "competition_risk": round(competition_risk, 3),
                "volatility_risk": round(volatility_risk, 3),
                "market_risk_score": market_risk_score,
                "risk_level": risk_level,
            })

        return {"status": "success", "scores": scores}
    except Exception as exc:
        return {"status": "error", "scores": [], "error": f"Market risk scoring failed: {exc}"}
