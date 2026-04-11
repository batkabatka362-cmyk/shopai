"""Product Risk Engine — financial risk scorer.

Assesses financial and margin risk per product: margin pressure,
price sensitivity, and capital exposure.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_MIN_HEALTHY_MARGIN = 0.20
_HIGH_PRICE_THRESHOLD = 200.0


def score_financial_risk(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score financial risk for each product.

    Args:
        products: List of product dicts.

    Returns:
        Structured dict with per-product financial risk scores.
    """
    try:
        items = copy.deepcopy(products)
        scores: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            price = float(item.get("price", 0.0))
            margin = float(item.get("margin", 0.0))

            # Margin risk: low margins = high risk
            if margin <= 0:
                margin_risk = 0.95
            elif margin < 0.10:
                margin_risk = 0.75
            elif margin < _MIN_HEALTHY_MARGIN:
                margin_risk = 0.50
            elif margin < 0.40:
                margin_risk = 0.20
            else:
                margin_risk = 0.10

            # Price risk: higher price = higher per-unit capital risk
            if price <= 0:
                price_risk = 0.10
            elif price < 25.0:
                price_risk = 0.15
            elif price < 100.0:
                price_risk = 0.30
            elif price < _HIGH_PRICE_THRESHOLD:
                price_risk = 0.55
            else:
                price_risk = 0.80

            # Capital risk: combination of price and margin
            capital_risk = round(
                price_risk * 0.5 + margin_risk * 0.5,
                3,
            )

            financial_risk_score = round(
                margin_risk * 0.45 + price_risk * 0.25 + capital_risk * 0.30,
                3,
            )

            if financial_risk_score < 0.25:
                risk_level = "low"
            elif financial_risk_score < 0.50:
                risk_level = "moderate"
            elif financial_risk_score < 0.75:
                risk_level = "high"
            else:
                risk_level = "critical"

            scores.append({
                "product_id": product_id,
                "margin_risk": round(margin_risk, 3),
                "price_risk": round(price_risk, 3),
                "capital_risk": capital_risk,
                "financial_risk_score": financial_risk_score,
                "risk_level": risk_level,
            })

        return {"status": "success", "scores": scores}
    except Exception as exc:
        return {"status": "error", "scores": [], "error": f"Financial risk scoring failed: {exc}"}
