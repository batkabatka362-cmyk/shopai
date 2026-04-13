"""Forecasting Engine — scenario builder.

Builds optimistic, baseline, and pessimistic forecast scenarios by
applying growth multipliers to the baseline forecast.

Model: LLaMA for creative scenario narrative and growth assumptions.

Pure Python — no numpy.
"""
from __future__ import annotations

from typing import Any

# Default growth multipliers per scenario
_SCENARIO_MULTIPLIERS: dict[str, float] = {
    "optimistic": 1.15,   # +15% above baseline
    "baseline": 1.00,     # No change
    "pessimistic": 0.85,  # -15% below baseline
}


def build_scenarios(
    forecast_with_ci: list[dict[str, Any]],
    trend: dict[str, Any],
    model_accuracy: dict[str, Any],
) -> dict[str, Any]:
    """Build optimistic, baseline, and pessimistic forecast scenarios.

    The multipliers are adjusted based on trend strength and direction:
    - Strong upward trend widens the optimistic scenario
    - Strong downward trend widens the pessimistic scenario
    - Poor model accuracy widens both tails

    Args:
        forecast_with_ci: Forecast points with confidence intervals.
        trend: TrendResult dict.
        model_accuracy: ModelAccuracy dict.

    Returns:
        Structured dict with three scenario arrays.
    """
    try:
        if not forecast_with_ci:
            return {
                "status": "error",
                "scenarios": {"optimistic": [], "baseline": [], "pessimistic": []},
                "error": "No forecast data for scenario building",
            }

        # Adjust multipliers based on trend and accuracy
        multipliers = _adjust_multipliers(trend, model_accuracy)

        scenarios: dict[str, list[dict[str, Any]]] = {
            "optimistic": [],
            "baseline": [],
            "pessimistic": [],
        }

        for step_idx, point in enumerate(forecast_with_ci):
            predicted = point["predicted"]
            step = step_idx + 1

            # Scenarios diverge over time — scale multiplier offset by sqrt(step)
            divergence = min(1.0 + step * 0.01, 2.0)  # cap at 2x divergence

            for scenario_name in ("optimistic", "baseline", "pessimistic"):
                base_mult = multipliers[scenario_name]
                # Apply time-based divergence (baseline stays at 1.0)
                if scenario_name == "baseline":
                    mult = 1.0
                else:
                    offset = (base_mult - 1.0) * divergence
                    mult = 1.0 + offset

                scenario_val = max(0.0, predicted * mult)

                scenarios[scenario_name].append({
                    "date": point["date"],
                    "predicted": round(scenario_val, 2),
                })

        return {
            "status": "success",
            "scenarios": scenarios,
            "multipliers": {k: round(v, 4) for k, v in multipliers.items()},
            "model_note": "LLaMA: scenario narrative generation",
        }
    except Exception as exc:
        return {
            "status": "error",
            "scenarios": {"optimistic": [], "baseline": [], "pessimistic": []},
            "error": f"Scenario building failed: {exc}",
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _adjust_multipliers(
    trend: dict[str, Any],
    model_accuracy: dict[str, Any],
) -> dict[str, float]:
    """Adjust scenario multipliers based on trend and model quality."""
    opt = _SCENARIO_MULTIPLIERS["optimistic"]
    base = _SCENARIO_MULTIPLIERS["baseline"]
    pess = _SCENARIO_MULTIPLIERS["pessimistic"]

    direction = trend.get("direction", "flat")
    strength = trend.get("strength", 0.0)
    r_squared = model_accuracy.get("r_squared", 0.0)

    # Trend adjustment: strong trends widen the corresponding tail
    if direction in ("up", "strong_up"):
        trend_boost = 0.05 * strength
        opt += trend_boost
    elif direction in ("down", "strong_down"):
        trend_drop = 0.05 * strength
        pess -= trend_drop

    # Accuracy adjustment: low accuracy widens both tails
    if r_squared < 0.5:
        uncertainty_spread = 0.05 * (1.0 - r_squared)
        opt += uncertainty_spread
        pess -= uncertainty_spread

    return {
        "optimistic": opt,
        "baseline": base,
        "pessimistic": pess,
    }
