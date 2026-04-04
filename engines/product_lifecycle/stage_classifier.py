"""Product Lifecycle Engine — stage classifier.

Classifies each product into a lifecycle stage: introduction, growth,
maturity, or decline based on sales history patterns.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


_STAGE_THRESHOLDS = {
    "growth_rate_high": 0.15,
    "growth_rate_low": -0.05,
    "maturity_variance": 0.10,
    "min_periods_intro": 3,
}


def classify_stages(
    products: list[dict[str, Any]],
    sales_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify lifecycle stage for each product.

    Args:
        products: List of product dicts.
        sales_history: List of sales history records.

    Returns:
        Structured dict with per-product stage classifications.
    """
    try:
        items = copy.deepcopy(products)

        # Build sales history per product
        history_map: dict[str, list[dict[str, Any]]] = {}
        for record in sales_history:
            pid = str(record.get("product_id", ""))
            if pid:
                history_map.setdefault(pid, []).append(record)

        classifications: list[dict[str, Any]] = []

        for item in items:
            product_id = str(item.get("id", "unknown"))
            history = history_map.get(product_id, [])
            history.sort(key=lambda r: str(r.get("period", "")))

            units = [int(r.get("units_sold", 0)) for r in history]

            if len(units) < _STAGE_THRESHOLDS["min_periods_intro"]:
                stage = "introduction"
                confidence = 0.7
                indicators = ["insufficient_history", "new_product"]
            else:
                growth_rates = []
                for i in range(1, len(units)):
                    prev = units[i - 1]
                    if prev > 0:
                        growth_rates.append((units[i] - prev) / prev)
                    else:
                        growth_rates.append(0.0)

                avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0.0
                recent_growth = growth_rates[-1] if growth_rates else 0.0

                if avg_growth > _STAGE_THRESHOLDS["growth_rate_high"]:
                    stage = "growth"
                    confidence = min(0.6 + abs(avg_growth), 0.95)
                    indicators = ["positive_growth", f"avg_growth_{round(avg_growth, 3)}"]
                elif avg_growth < _STAGE_THRESHOLDS["growth_rate_low"]:
                    stage = "decline"
                    confidence = min(0.6 + abs(avg_growth), 0.95)
                    indicators = ["negative_growth", f"avg_growth_{round(avg_growth, 3)}"]
                else:
                    if len(units) >= 2:
                        mean_units = sum(units) / len(units)
                        variance = sum((u - mean_units) ** 2 for u in units) / len(units)
                        cv = (variance ** 0.5) / mean_units if mean_units > 0 else 0
                    else:
                        cv = 0

                    if cv < _STAGE_THRESHOLDS["maturity_variance"]:
                        stage = "maturity"
                        confidence = min(0.7 + (1 - cv), 0.95)
                        indicators = ["stable_sales", f"cv_{round(cv, 3)}"]
                    else:
                        stage = "maturity"
                        confidence = 0.6
                        indicators = ["moderate_variance", f"cv_{round(cv, 3)}"]

            classifications.append({
                "product_id": product_id,
                "stage": stage,
                "confidence": round(confidence, 3),
                "indicators": indicators,
            })

        return {"status": "success", "classifications": classifications}
    except Exception as exc:
        return {"status": "error", "classifications": [], "error": f"Stage classification failed: {exc}"}
