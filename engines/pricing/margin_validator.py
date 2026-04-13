"""Pricing Engine — margin validator.

Validates that a proposed price meets margin requirements: covers all costs
(floor check), stays within market tolerance (ceiling check), meets the
target margin, and assesses volume sensitivity at different price points.

Model note: Uses Mistral for margin analysis and volume sensitivity.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Market ceiling multipliers by demand level
# ---------------------------------------------------------------------------

_CEILING_MULTIPLIERS: dict[str, float] = {
    "very_high": 1.80,
    "high": 1.50,
    "medium": 1.30,
    "low": 1.15,
    "very_low": 1.05,
}

_DEFAULT_CEILING_MULTIPLIER = 1.30


def validate_margin(
    proposed_price: float,
    cost_analysis: dict[str, Any],
    competitor_mapping: dict[str, Any],
    target_margin: float,
    demand_level: str,
) -> dict[str, Any]:
    """Validate that the proposed price meets margin and market constraints.

    Args:
        proposed_price: The price to validate.
        cost_analysis: CostAnalysis from cost_analyzer.
        competitor_mapping: CompetitorPrices from competitor_price_mapper.
        target_margin: Desired profit margin as decimal.
        demand_level: Current demand level string.

    Returns:
        Structured dict with MarginCheck data.
    """
    try:
        costs = copy.deepcopy(cost_analysis)
        comp = copy.deepcopy(competitor_mapping)

        price = float(proposed_price)
        total_cost = float(costs.get("total_cost", 0.0))
        cost_floor = float(costs.get("cost_floor", 0.0))
        max_competitor = float(comp.get("max_price", 0.0))
        avg_price = float(comp.get("avg_price", 0.0))
        target = min(max(float(target_margin), 0.0), 0.99)
        demand = demand_level.lower() if demand_level else "medium"

        # --- Floor check: must cover all costs ---
        covers_costs = price >= cost_floor

        # --- Margin at this price ---
        # margin = (price - total_cost) / price
        if price > 0:
            margin_at_price = (price - total_cost) / price
        else:
            margin_at_price = -1.0

        meets_target = margin_at_price >= target

        # --- Ceiling: max market tolerance ---
        # Ceiling is the highest competitor price * demand multiplier
        ceiling_mult = _CEILING_MULTIPLIERS.get(demand, _DEFAULT_CEILING_MULTIPLIER)
        if max_competitor > 0:
            ceiling_price = max_competitor * ceiling_mult
        elif avg_price > 0:
            ceiling_price = avg_price * ceiling_mult
        else:
            # No competitor data — use cost-based ceiling
            ceiling_price = cost_floor * 3.0

        ceiling_price = round(ceiling_price, 2)
        floor_price = round(cost_floor, 2)

        # --- Volume sensitivity ---
        # Estimate how volume changes at different price points relative to avg
        volume_sensitivity = _compute_volume_sensitivity(
            price, cost_floor, avg_price, ceiling_price,
        )

        # --- Overall margin health ---
        margin_health = _assess_margin_health(
            margin_at_price, target, covers_costs, price, ceiling_price,
        )

        return {
            "status": "success",
            "validation": {
                "margin_at_price": round(margin_at_price, 4),
                "covers_costs": covers_costs,
                "meets_target": meets_target,
                "floor_price": floor_price,
                "ceiling_price": ceiling_price,
                "volume_sensitivity": volume_sensitivity,
                "margin_health": margin_health,
                "model_note": "Mistral: margin validation and volume sensitivity analysis",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "validation": {},
            "error": f"Margin validation failed: {exc}",
        }


def _compute_volume_sensitivity(
    price: float,
    cost_floor: float,
    avg_price: float,
    ceiling: float,
) -> dict[str, float]:
    """Estimate relative volume at different price points.

    Uses a linear demand model: volume drops as price rises above average,
    increases as price drops below average. Returns multipliers relative
    to a baseline volume of 1.0 at the average market price.
    """
    if avg_price <= 0:
        return {"at_price": 1.0, "at_floor": 1.0, "at_ceiling": 1.0}

    def _volume_multiplier(p: float) -> float:
        # Linear elasticity: every 10% above avg = 15% volume drop
        deviation = (p - avg_price) / avg_price
        multiplier = 1.0 - (deviation * 1.5)
        return round(max(multiplier, 0.05), 2)

    return {
        "at_price": _volume_multiplier(price),
        "at_floor": _volume_multiplier(cost_floor),
        "at_ceiling": _volume_multiplier(ceiling),
    }


def _assess_margin_health(
    margin: float,
    target: float,
    covers_costs: bool,
    price: float,
    ceiling: float,
) -> str:
    """Classify overall margin health."""
    if not covers_costs:
        return "critical"
    if margin < 0:
        return "negative"
    if margin < target * 0.5:
        return "poor"
    if margin < target:
        return "below_target"
    if price > ceiling:
        return "overpriced"
    if margin >= target * 1.2:
        return "excellent"
    return "healthy"
