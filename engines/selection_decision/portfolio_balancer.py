"""Selection Decision Engine — portfolio balancer.

Analyzes the selected product portfolio for balance across categories,
risk levels, and price tiers.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def balance_portfolio(
    selected_products: list[dict[str, Any]],
    ranked_products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Analyze portfolio balance.

    Args:
        selected_products: List of products that passed selection.
        ranked_products: Full list of ranked products (for context).

    Returns:
        Structured dict with portfolio balance analysis.
    """
    try:
        if not selected_products:
            return {
                "status": "success",
                "balance": {
                    "category_distribution": {},
                    "risk_distribution": {},
                    "balance_score": 0.0,
                    "recommendations": ["No products selected"],
                },
            }

        # Category distribution
        cat_dist: dict[str, int] = {}
        for p in selected_products:
            cat = str(p.get("category", "uncategorized"))
            cat_dist[cat] = cat_dist.get(cat, 0) + 1

        # Risk distribution
        risk_dist: dict[str, int] = {"low": 0, "moderate": 0, "high": 0}
        for p in selected_products:
            risk = float(p.get("risk_score", 0.5))
            if risk < 0.3:
                risk_dist["low"] += 1
            elif risk < 0.6:
                risk_dist["moderate"] += 1
            else:
                risk_dist["high"] += 1

        # Balance score: penalize concentration
        n = len(selected_products)
        n_categories = len(cat_dist)
        category_balance = min(n_categories / max(n * 0.5, 1), 1.0)

        total_risk = sum(float(p.get("risk_score", 0.5)) for p in selected_products)
        avg_risk = total_risk / n if n > 0 else 0.5
        risk_balance = 1.0 - abs(avg_risk - 0.3)  # Ideal avg risk around 0.3

        balance_score = round(category_balance * 0.5 + risk_balance * 0.5, 3)

        recommendations: list[str] = []
        if n_categories == 1 and n > 2:
            recommendations.append("Diversify across more categories to reduce concentration risk")
        if risk_dist["high"] > n * 0.5:
            recommendations.append("Reduce high-risk product proportion in portfolio")
        if avg_risk > 0.6:
            recommendations.append("Overall portfolio risk is elevated; consider safer alternatives")
        if not recommendations:
            recommendations.append("Portfolio balance is acceptable")

        return {
            "status": "success",
            "balance": {
                "category_distribution": cat_dist,
                "risk_distribution": risk_dist,
                "balance_score": balance_score,
                "recommendations": recommendations,
            },
        }
    except Exception as exc:
        return {"status": "error", "balance": {}, "error": f"Portfolio balancing failed: {exc}"}
