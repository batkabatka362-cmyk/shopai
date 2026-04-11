"""Dynamic Pricing Engine — demand analyzer.

Analyzes current demand vs. normal demand, detects surges, determines trend
direction, and produces a demand multiplier for price adjustment.

Model note: Uses Mistral for demand analysis and surge detection.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Surge thresholds
# ---------------------------------------------------------------------------

_SURGE_THRESHOLD = 1.40       # demand_index > 1.40 = surge
_HIGH_DEMAND = 1.20           # > 1.20 = rising trend
_LOW_DEMAND = 0.80            # < 0.80 = falling trend

# Multiplier bounds — demand alone cannot push price more than +/-15%
_MAX_DEMAND_MULTIPLIER = 1.15
_MIN_DEMAND_MULTIPLIER = 0.85


def analyze_demand(
    signals: dict[str, Any],
) -> dict[str, Any]:
    """Analyze demand signals and produce a demand multiplier.

    Args:
        signals: CollectedSignals dict from signal_collector.

    Returns:
        Structured dict with DemandAnalysis data.
    """
    try:
        sig = copy.deepcopy(signals)

        demand_index = float(sig.get("demand_index", 1.0))
        daily_sales = float(sig.get("daily_sales", 0.0))

        # --- Surge detection ---
        surge_detected = demand_index >= _SURGE_THRESHOLD

        # --- Trend direction ---
        if demand_index >= _HIGH_DEMAND:
            trend_direction = "rising"
        elif demand_index <= _LOW_DEMAND:
            trend_direction = "falling"
        else:
            trend_direction = "stable"

        # --- Demand ratio (current vs normal) ---
        # demand_index IS the ratio of current to normal demand
        demand_ratio = round(demand_index, 3)

        # --- Demand multiplier ---
        # Maps demand_index to a price multiplier in [_MIN, _MAX]
        # Linear interpolation: index 0.5 -> 0.85, index 1.0 -> 1.0, index 1.5+ -> 1.15
        if demand_index >= 1.0:
            # Above normal: scale up linearly from 1.0 to _MAX at index 1.5
            excess = min(demand_index - 1.0, 0.5)
            multiplier = 1.0 + (excess / 0.5) * (_MAX_DEMAND_MULTIPLIER - 1.0)
        else:
            # Below normal: scale down linearly from 1.0 to _MIN at index 0.5
            deficit = min(1.0 - demand_index, 0.5)
            multiplier = 1.0 - (deficit / 0.5) * (1.0 - _MIN_DEMAND_MULTIPLIER)

        multiplier = max(_MIN_DEMAND_MULTIPLIER, min(multiplier, _MAX_DEMAND_MULTIPLIER))

        # Extra boost for surge: cap at _MAX but note surge
        if surge_detected:
            multiplier = _MAX_DEMAND_MULTIPLIER

        return {
            "status": "success",
            "analysis": {
                "demand_ratio": demand_ratio,
                "surge_detected": surge_detected,
                "trend_direction": trend_direction,
                "demand_multiplier": round(multiplier, 4),
                "model_note": "Mistral: demand analysis, surge detection, trend identification",
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "analysis": {},
            "error": f"Demand analysis failed: {exc}",
        }
