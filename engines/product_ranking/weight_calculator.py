"""Product Ranking Engine — weight calculator.

Applies weighted scoring criteria to each product dimension.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any

_DEFAULT_WEIGHTS = {"demand": 0.30, "margin": 0.30, "competition": 0.25, "risk_penalty": 0.15}


def calculate_weights(
    products: list[dict[str, Any]],
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply weighted scoring to products.

    Args:
        products: List of product dicts with dimension scores.
        criteria: Weight overrides.

    Returns:
        Structured dict with weighted products.
    """
    try:
        items = copy.deepcopy(products)
        criteria = criteria or {}
        weights = {
            "demand": float(criteria.get("demand_weight", _DEFAULT_WEIGHTS["demand"])),
            "margin": float(criteria.get("margin_weight", _DEFAULT_WEIGHTS["margin"])),
            "competition": float(criteria.get("competition_weight", _DEFAULT_WEIGHTS["competition"])),
        }
        risk_penalty = float(criteria.get("risk_penalty", _DEFAULT_WEIGHTS["risk_penalty"]))

        total_w = sum(weights.values()) or 1.0
        weights = {k: v / total_w for k, v in weights.items()}

        result: list[dict[str, Any]] = []
        for item in items:
            d = float(item.get("demand_score", 0.0))
            m = float(item.get("margin_score", 0.0))
            c = float(item.get("competition_score", 0.0))
            risk = str(item.get("risk_level", "low"))

            risk_mult = {"low": 1.0, "medium": 0.9, "high": 0.75, "critical": 0.5}.get(risk, 0.85)

            weighted = {
                "demand": round(d * weights["demand"], 3),
                "margin": round(m * weights["margin"], 3),
                "competition": round(c * weights["competition"], 3),
            }
            raw = sum(weighted.values())
            final = round(raw * (1.0 - risk_penalty + risk_penalty * risk_mult), 3)

            item["weighted_scores"] = weighted
            item["final_score"] = final
            result.append(item)

        return {"status": "success", "weighted_products": result}
    except Exception as exc:
        return {"status": "error", "weighted_products": [], "error": f"Weight calculation failed: {exc}"}
