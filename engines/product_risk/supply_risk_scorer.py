"""Product Risk Engine — supply risk scorer.

Assesses supply chain risk per product: lead time exposure,
supplier reliability, and concentration risk.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_LEAD_TIME_THRESHOLDS = {"fast": 7, "moderate": 21, "slow": 45}


def score_supply_risk(
    products: list[dict[str, Any]],
    suppliers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Score supply chain risk for each product.

    Args:
        products: List of product dicts.
        suppliers: List of supplier info dicts.

    Returns:
        Structured dict with per-product supply risk scores.
    """
    try:
        items = copy.deepcopy(products)
        sup_map: dict[str, dict[str, Any]] = {}
        for s in suppliers:
            sid = str(s.get("id", ""))
            if sid:
                sup_map[sid] = s

        scores: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            supplier_id = str(item.get("supplier_id", ""))
            supplier = sup_map.get(supplier_id, {})

            lead_time = int(supplier.get("lead_time_days", 30))
            reliability = float(supplier.get("reliability_score", 0.5))
            backup = bool(supplier.get("backup_available", False))

            # Lead time risk: longer lead times = higher risk
            if lead_time <= _LEAD_TIME_THRESHOLDS["fast"]:
                lead_time_risk = 0.10
            elif lead_time <= _LEAD_TIME_THRESHOLDS["moderate"]:
                lead_time_risk = 0.35
            elif lead_time <= _LEAD_TIME_THRESHOLDS["slow"]:
                lead_time_risk = 0.65
            else:
                lead_time_risk = 0.90

            # Reliability risk: inverse of reliability score
            reliability_risk = round(1.0 - min(max(reliability, 0.0), 1.0), 3)

            # Concentration risk: no backup = high concentration
            concentration_risk = 0.20 if backup else 0.70

            supply_risk_score = round(
                lead_time_risk * 0.35 + reliability_risk * 0.40 + concentration_risk * 0.25,
                3,
            )

            if supply_risk_score < 0.25:
                risk_level = "low"
            elif supply_risk_score < 0.50:
                risk_level = "moderate"
            elif supply_risk_score < 0.75:
                risk_level = "high"
            else:
                risk_level = "critical"

            scores.append({
                "product_id": product_id,
                "lead_time_risk": round(lead_time_risk, 3),
                "reliability_risk": reliability_risk,
                "concentration_risk": round(concentration_risk, 3),
                "supply_risk_score": supply_risk_score,
                "risk_level": risk_level,
            })

        return {"status": "success", "scores": scores}
    except Exception as exc:
        return {"status": "error", "scores": [], "error": f"Supply risk scoring failed: {exc}"}
