"""Warranty Engine — risk analyzer.

Analyzes warranty risk by product: claim frequency,
severity patterns, and risk predictions.
"""
from __future__ import annotations

import copy
from typing import Any


def analyze_risk(
    claims_processed: dict[str, Any],
    products: list[dict[str, Any]],
    costs: dict[str, Any],
) -> dict[str, Any]:
    """Analyze warranty risk by product.

    Args:
        claims_processed: Processed claims data.
        products: Product records.
        costs: Cost tracking data.

    Returns:
        Structured dict with risk analysis and recommendations.
    """
    try:
        details = claims_processed.get("details", [])
        prods = copy.deepcopy(products)

        # Claims per product
        claims_per_prod: dict[str, int] = {}
        for claim in details:
            pid = claim.get("product_id", "")
            claims_per_prod[pid] = claims_per_prod.get(pid, 0) + 1

        # Build product lookup
        prod_map = {str(p.get("id", "")): p for p in prods}

        risk_analysis: list[dict[str, Any]] = []
        recommendations: list[str] = []

        for pid, claim_count in sorted(claims_per_prod.items(), key=lambda x: x[1], reverse=True):
            prod = prod_map.get(pid, {})
            sold = float(prod.get("quantity_sold", 1))
            claim_rate = round(claim_count / sold * 100, 2) if sold > 0 else 0.0

            cost_per_product = float(costs.get("cost_by_product", {}).get(pid, 0))

            if claim_rate > 10:
                risk_level = "high"
            elif claim_rate > 5:
                risk_level = "medium"
            else:
                risk_level = "low"

            risk_analysis.append({
                "product_id": pid,
                "title": str(prod.get("title", "")),
                "claim_count": claim_count,
                "claim_rate_pct": claim_rate,
                "total_cost": round(cost_per_product, 2),
                "risk_level": risk_level,
            })

        # Generate recommendations
        high_risk = [r for r in risk_analysis if r["risk_level"] == "high"]
        if high_risk:
            recommendations.append(f"{len(high_risk)} products have high warranty risk — investigate quality issues")
            for hr in high_risk[:3]:
                recommendations.append(f"Product '{hr['title']}': {hr['claim_rate_pct']}% claim rate — consider quality review")

        warranty_pct = float(costs.get("warranty_cost_pct_of_revenue", 0))
        if warranty_pct > 3:
            recommendations.append(f"Warranty costs are {warranty_pct}% of revenue — above industry benchmark of 2-3%")

        if not recommendations:
            recommendations.append("Warranty risk is within normal ranges — continue monitoring")

        return {
            "status": "success",
            "risk_analysis": risk_analysis,
            "policy_recommendations": recommendations,
        }
    except Exception as exc:
        return {
            "status": "error",
            "risk_analysis": [],
            "error": f"Risk analysis failed: {exc}",
        }
