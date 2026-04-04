"""Price Elasticity Engine — demand curve builder.

Builds a demand curve for each product by fitting price-quantity
relationships from historical data.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def build_demand_curves(
    products: list[dict[str, Any]],
    price_history: list[dict[str, Any]],
    sensitivities: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build demand curves for each product.

    Args:
        products: List of product dicts.
        price_history: List of price history records.
        sensitivities: Per-product sensitivity results.

    Returns:
        Structured dict with per-product demand curves.
    """
    try:
        history_map: dict[str, list[dict[str, Any]]] = {}
        for record in price_history:
            pid = str(record.get("product_id", ""))
            if pid:
                history_map.setdefault(pid, []).append(record)

        sens_map = {str(s.get("product_id", "")): s for s in sensitivities}

        curves: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            history = history_map.get(pid, [])
            current_price = float(item.get("current_price", 0))
            sens = sens_map.get(pid, {})
            coeff = float(sens.get("elasticity_coefficient", -1.0))

            prices = [float(r.get("price", 0)) for r in history]
            quantities = [int(r.get("units_sold", 0)) for r in history]

            if not prices or not quantities or current_price <= 0:
                curves.append({
                    "product_id": pid,
                    "curve_points": [],
                    "r_squared": 0.0,
                })
                continue

            # Use linear regression: Q = a + b * P
            n = len(prices)
            mean_p = sum(prices) / n
            mean_q = sum(quantities) / n

            ss_pp = sum((p - mean_p) ** 2 for p in prices)
            ss_pq = sum((prices[i] - mean_p) * (quantities[i] - mean_q) for i in range(n))

            if ss_pp > 0:
                b = ss_pq / ss_pp
                a = mean_q - b * mean_p

                # R-squared
                ss_total = sum((q - mean_q) ** 2 for q in quantities)
                ss_residual = sum((quantities[i] - (a + b * prices[i])) ** 2 for i in range(n))
                r_squared = round(1 - ss_residual / ss_total, 3) if ss_total > 0 else 0.0
            else:
                a = mean_q
                b = 0.0
                r_squared = 0.0

            # Generate curve points at 5 price levels around current
            curve_points = []
            for pct in [0.70, 0.85, 1.00, 1.15, 1.30]:
                test_price = round(current_price * pct, 2)
                predicted_demand = max(0, int(a + b * test_price))
                curve_points.append({
                    "price": test_price,
                    "predicted_demand": predicted_demand,
                })

            curves.append({
                "product_id": pid,
                "curve_points": curve_points,
                "r_squared": max(r_squared, 0.0),
            })

        return {"status": "success", "curves": curves}
    except Exception as exc:
        return {"status": "error", "curves": [], "error": f"Demand curve building failed: {exc}"}
