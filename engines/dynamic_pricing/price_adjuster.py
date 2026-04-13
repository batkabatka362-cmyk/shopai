"""Dynamic Pricing Engine — price adjuster.

Combines all signal multipliers with configurable weights, applies
floor/ceiling constraints, and produces the adjusted price.

Model note: Uses Qwen for structured adjustment output.

1 file = 1 job: price adjustment calculation only.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Signal weights (must sum to 1.0)
# ---------------------------------------------------------------------------

_DEFAULT_WEIGHTS: dict[str, float] = {
    "demand": 0.30,
    "competition": 0.25,
    "inventory": 0.25,
    "time": 0.20,
}

# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

_MAX_INCREASE_PCT = 20.0   # max +20% from current price
_MAX_DECREASE_PCT = 20.0   # max -20% from current price
_MIN_MARGIN_PCT = 5.0      # minimum margin above COGS (%)


def adjust_price(
    signals: dict[str, Any],
    demand_analysis: dict[str, Any],
    competition_snapshot: dict[str, Any],
    inventory_assessment: dict[str, Any],
    time_factors: dict[str, Any],
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Calculate adjusted price from all signal multipliers.

    Weighted combination of individual multipliers, then constrained
    by floor (COGS + min margin) and ceiling (max % change).

    Args:
        signals: CollectedSignals dict.
        demand_analysis: DemandAnalysis from demand_analyzer.
        competition_snapshot: CompetitionSnapshot from competition_monitor.
        inventory_assessment: InventoryAssessment from inventory_assessor.
        time_factors: TimeFactors from time_factor_analyzer.
        weights: Optional override for signal weights.

    Returns:
        Structured dict with PriceAdjustment data.
    """
    try:
        sig = copy.deepcopy(signals)
        w = copy.deepcopy(weights) if weights else copy.deepcopy(_DEFAULT_WEIGHTS)

        current_price = float(sig.get("current_price", 0.0))
        cogs = float(sig.get("cogs", 0.0))
        product_id = str(sig.get("product_id", "unknown"))

        if current_price <= 0:
            return {
                "status": "error",
                "adjustment": {},
                "error": "Current price must be positive",
            }

        # --- Extract individual multipliers ---
        demand_mult = float(demand_analysis.get("demand_multiplier", 1.0))
        inventory_mult = float(inventory_assessment.get("inventory_multiplier", 1.0))
        time_mult = float(time_factors.get("time_multiplier", 1.0))

        # Competition multiplier: derived from competitive pressure
        # High pressure (we are expensive) -> push price down
        # Low pressure (we are cheap) -> allow price up
        competitive_pressure = float(competition_snapshot.get("competitive_pressure", 0.0))
        competition_mult = 1.0 - (competitive_pressure * 0.15)  # max -15% from competition

        # --- Weighted combination ---
        # Each multiplier is a factor around 1.0.
        # Weighted blend: sum of (weight_i * multiplier_i)
        total_weight = sum(w.values()) or 1.0
        raw_multiplier = (
            w.get("demand", 0.30) * demand_mult
            + w.get("competition", 0.25) * competition_mult
            + w.get("inventory", 0.25) * inventory_mult
            + w.get("time", 0.20) * time_mult
        ) / total_weight

        # --- Apply multiplier to current price ---
        raw_new_price = current_price * raw_multiplier

        # --- Floor constraint: COGS + minimum margin ---
        floor_price = cogs * (1.0 + _MIN_MARGIN_PCT / 100.0) if cogs > 0 else 0.0

        # --- Ceiling constraint: max % change from current ---
        max_price = current_price * (1.0 + _MAX_INCREASE_PCT / 100.0)
        min_price = current_price * (1.0 - _MAX_DECREASE_PCT / 100.0)

        # Apply constraints
        new_price = raw_new_price
        new_price = max(new_price, floor_price)
        new_price = max(new_price, min_price)
        new_price = min(new_price, max_price)

        # Round to 2 decimals
        new_price = round(new_price, 2)

        change_pct = round(
            ((new_price - current_price) / current_price) * 100.0, 2,
        )

        return {
            "status": "success",
            "adjustment": {
                "product_id": product_id,
                "current_price": round(current_price, 2),
                "new_price": new_price,
                "change_pct": change_pct,
                "raw_multiplier": round(raw_multiplier, 4),
                "signal_weights": w,
                "model_note": "Qwen: structured price adjustment with weighted signal combination",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "adjustment": {},
            "error": f"Price adjustment failed: {exc}",
        }
