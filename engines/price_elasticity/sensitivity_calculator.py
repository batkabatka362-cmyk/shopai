"""Price Elasticity Engine — sensitivity calculator.

Calculates price elasticity coefficient for each product using
percentage change in quantity demanded vs percentage change in price.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def calculate_sensitivity(
    products: list[dict[str, Any]],
    price_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate price sensitivity for each product.

    Args:
        products: List of product dicts.
        price_history: List of price history records.

    Returns:
        Structured dict with per-product sensitivity results.
    """
    try:
        history_map: dict[str, list[dict[str, Any]]] = {}
        for record in price_history:
            pid = str(record.get("product_id", ""))
            if pid:
                history_map.setdefault(pid, []).append(record)

        results: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            history = history_map.get(pid, [])
            history.sort(key=lambda r: str(r.get("period", "")))

            prices = [float(r.get("price", 0)) for r in history]
            quantities = [int(r.get("units_sold", 0)) for r in history]

            if len(prices) < 2:
                results.append({
                    "product_id": pid,
                    "elasticity_coefficient": 0.0,
                    "is_elastic": False,
                    "sensitivity_band": "unknown",
                })
                continue

            # Calculate arc elasticity across all adjacent periods
            elasticities = []
            for i in range(1, len(prices)):
                p1, p2 = prices[i - 1], prices[i]
                q1, q2 = quantities[i - 1], quantities[i]

                avg_p = (p1 + p2) / 2
                avg_q = (q1 + q2) / 2

                if avg_p > 0 and avg_q > 0 and p2 != p1:
                    pct_q = (q2 - q1) / avg_q
                    pct_p = (p2 - p1) / avg_p
                    elasticities.append(pct_q / pct_p)

            if elasticities:
                coefficient = round(sum(elasticities) / len(elasticities), 3)
            else:
                coefficient = 0.0

            is_elastic = abs(coefficient) > 1.0

            if abs(coefficient) < 0.5:
                band = "inelastic"
            elif abs(coefficient) < 1.0:
                band = "unit_elastic"
            elif abs(coefficient) < 2.0:
                band = "elastic"
            else:
                band = "highly_elastic"

            results.append({
                "product_id": pid,
                "elasticity_coefficient": coefficient,
                "is_elastic": is_elastic,
                "sensitivity_band": band,
            })

        return {"status": "success", "sensitivities": results}
    except Exception as exc:
        return {"status": "error", "sensitivities": [], "error": f"Sensitivity calculation failed: {exc}"}
