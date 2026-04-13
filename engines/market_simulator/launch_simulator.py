"""Market Simulator Engine — launch simulator.

Simulates new product launch outcomes using adoption curves and market data.
"""
from __future__ import annotations

import copy
import math
from typing import Any


def simulate_launch(
    scenarios: list[dict[str, Any]],
    demand_model: dict[str, Any],
    product: dict[str, Any],
    market_data: dict[str, Any],
) -> dict[str, Any]:
    """Simulate product launch outcomes for each scenario."""
    try:
        scenarios = copy.deepcopy(scenarios)
        market_size = float(market_data.get("market_size", 100000))
        base_price = float(product.get("price", 0.0))

        simulations: list[dict[str, Any]] = []
        for scenario in scenarios:
            name = str(scenario.get("name", "unnamed"))
            marketing_spend = float(scenario.get("marketing_spend", 0.0))

            awareness_rate = min(0.9, 0.05 + (marketing_spend / max(market_size, 1)) * 2)
            conversion_rate = 0.02 + awareness_rate * 0.03
            first_month_units = round(market_size * awareness_rate * conversion_rate, 0)

            adoption_curve = []
            cumulative_units = 0
            for month in range(1, 4):
                growth_factor = 1.0 / (1.0 + math.exp(-0.5 * (month - 2)))
                month_units = round(first_month_units * growth_factor * (1 + 0.3 * (month - 1)), 0)
                cumulative_units += month_units
                adoption_curve.append({
                    "month": month, "units": month_units,
                    "cumulative_units": cumulative_units,
                    "revenue": round(month_units * base_price, 2),
                })

            simulations.append({
                "scenario": name,
                "adoption_curve": adoption_curve,
                "predicted_first_month_units": first_month_units,
                "predicted_first_quarter_revenue": round(cumulative_units * base_price, 2),
                "market_share_estimate": round(cumulative_units / max(market_size, 1) * 100, 4),
            })

        return {"status": "success", "simulations": simulations}
    except Exception as exc:
        return {"status": "error", "simulations": [], "error": f"Launch simulation failed: {exc}"}
