"""Market Simulator Engine — price impact simulator.

Simulates the revenue/unit impact of price changes using demand model data.
"""
from __future__ import annotations

import copy
from typing import Any


def simulate_price_impact(
    scenarios: list[dict[str, Any]],
    demand_model: dict[str, Any],
    product: dict[str, Any],
) -> dict[str, Any]:
    """Simulate price change impacts for each scenario."""
    try:
        scenarios = copy.deepcopy(scenarios)
        base_price = float(product.get("price", 0.0))
        base_units = float(demand_model.get("base_demand", 0.0))
        elasticity = float(demand_model.get("price_elasticity", -1.2))
        base_cost = float(product.get("unit_cost", base_price * 0.6))

        impacts: list[dict[str, Any]] = []
        for scenario in scenarios:
            name = str(scenario.get("name", "unnamed"))
            price_pct = float(scenario.get("price_change_pct", 0.0))

            demand_change_pct = price_pct * elasticity / 100.0
            new_units = max(round(base_units * (1 + demand_change_pct), 1), 0)
            new_price = round(base_price * (1 + price_pct / 100.0), 2)
            new_revenue = round(new_units * new_price, 2)

            old_margin = (base_price - base_cost) * base_units
            new_margin = (new_price - base_cost) * new_units
            margin_impact = round(new_margin - old_margin, 2)

            impacts.append({
                "scenario": name,
                "price_change_pct": price_pct,
                "demand_change_pct": round(demand_change_pct * 100, 2),
                "predicted_revenue": new_revenue,
                "predicted_units": new_units,
                "margin_impact": margin_impact,
            })

        return {"status": "success", "impacts": impacts}
    except Exception as exc:
        return {"status": "error", "impacts": [], "error": f"Price impact simulation failed: {exc}"}
