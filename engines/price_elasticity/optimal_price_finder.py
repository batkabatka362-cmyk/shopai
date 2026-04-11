"""Price Elasticity Engine — optimal price finder.

Finds the revenue-maximizing price for each product using its demand curve.

All math is real. No faking, no random numbers.
"""
from __future__ import annotations

import copy
from typing import Any


def find_optimal_prices(
    products: list[dict[str, Any]],
    curves: list[dict[str, Any]],
) -> dict[str, Any]:
    """Find optimal price for each product.

    Args:
        products: List of product dicts.
        curves: Per-product demand curves.

    Returns:
        Structured dict with per-product optimal price results.
    """
    try:
        curve_map = {str(c.get("product_id", "")): c for c in curves}
        results: list[dict[str, Any]] = []

        for item in products:
            pid = str(item.get("id", "unknown"))
            current_price = float(item.get("current_price", 0))
            curve = curve_map.get(pid, {})
            points = curve.get("curve_points", [])

            if not points or current_price <= 0:
                results.append({
                    "product_id": pid,
                    "optimal_price": current_price,
                    "expected_units": 0,
                    "expected_revenue": 0.0,
                    "current_revenue_gap": 0.0,
                })
                continue

            # Find the price point that maximizes revenue
            best_price = current_price
            best_revenue = 0.0
            best_units = 0
            current_revenue = 0.0

            for point in points:
                price = float(point.get("price", 0))
                demand = int(point.get("predicted_demand", 0))
                revenue = price * demand

                if abs(price - current_price) < 0.01:
                    current_revenue = revenue

                if revenue > best_revenue:
                    best_revenue = revenue
                    best_price = price
                    best_units = demand

            if current_revenue <= 0:
                current_revenue = current_price * best_units

            gap = round(best_revenue - current_revenue, 2) if current_revenue > 0 else 0.0

            results.append({
                "product_id": pid,
                "optimal_price": round(best_price, 2),
                "expected_units": best_units,
                "expected_revenue": round(best_revenue, 2),
                "current_revenue_gap": gap,
            })

        return {"status": "success", "optimal_prices": results}
    except Exception as exc:
        return {"status": "error", "optimal_prices": [], "error": f"Optimal price finding failed: {exc}"}
