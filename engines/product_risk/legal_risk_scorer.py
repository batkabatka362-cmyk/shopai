"""Product Risk Engine — legal risk scorer.

Assesses legal and compliance risk per product: regulatory exposure,
compliance complexity, and liability potential.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_HIGH_RISK_CATEGORIES = {"supplements", "electronics", "cosmetics", "food", "children", "medical"}
_REGULATED_KEYWORDS = {"organic", "natural", "medical", "therapeutic", "fda", "certified"}


def score_legal_risk(
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score legal/compliance risk for each product.

    Args:
        products: List of product dicts.

    Returns:
        Structured dict with per-product legal risk scores.
    """
    try:
        items = copy.deepcopy(products)
        scores: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            category = str(item.get("category", "")).lower()
            title = str(item.get("title", "")).lower()

            # Compliance risk: category-based
            if category in _HIGH_RISK_CATEGORIES:
                compliance_risk = 0.70
            else:
                compliance_risk = 0.20

            # Liability risk: keyword-based claims scanning
            keyword_hits = sum(1 for kw in _REGULATED_KEYWORDS if kw in title)
            liability_risk = min(0.15 + keyword_hits * 0.20, 1.0)

            # Regulatory risk: combination of category and claims
            regulatory_risk = round(
                compliance_risk * 0.6 + liability_risk * 0.4,
                3,
            )

            legal_risk_score = round(
                compliance_risk * 0.40 + liability_risk * 0.30 + regulatory_risk * 0.30,
                3,
            )

            if legal_risk_score < 0.25:
                risk_level = "low"
            elif legal_risk_score < 0.50:
                risk_level = "moderate"
            elif legal_risk_score < 0.75:
                risk_level = "high"
            else:
                risk_level = "critical"

            scores.append({
                "product_id": product_id,
                "compliance_risk": round(compliance_risk, 3),
                "liability_risk": round(liability_risk, 3),
                "regulatory_risk": regulatory_risk,
                "legal_risk_score": legal_risk_score,
                "risk_level": risk_level,
            })

        return {"status": "success", "scores": scores}
    except Exception as exc:
        return {"status": "error", "scores": [], "error": f"Legal risk scoring failed: {exc}"}
