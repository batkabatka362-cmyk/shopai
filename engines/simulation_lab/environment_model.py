"""Simulation Lab — environment model.

Models market/store environment conditions: seasonality, competition,
demand curves, volatility, and store maturity. Produces a set of
multipliers that the simulation engine applies to each iteration.

Model note: Would use Mistral for analysis/validation of environment assumptions.
"""
from __future__ import annotations

import copy
from typing import Any


# ---------------------------------------------------------------------------
# Seasonality multipliers by category hint
# ---------------------------------------------------------------------------

_SEASON_MULTIPLIERS: dict[str, dict[str, float]] = {
    "spring": {"default": 1.05, "garden": 1.35, "fashion": 1.15, "outdoor": 1.25},
    "summer": {"default": 0.95, "garden": 1.20, "fashion": 1.00, "outdoor": 1.40, "travel": 1.30},
    "fall":   {"default": 1.10, "fashion": 1.20, "electronics": 1.15, "home": 1.10},
    "winter": {"default": 1.25, "electronics": 1.40, "toys": 1.60, "fashion": 1.15, "outdoor": 0.70},
}

_MATURITY_MODIFIERS: dict[str, float] = {
    "new": 0.70,
    "growing": 0.90,
    "established": 1.10,
}

_DEMAND_TREND_MODIFIERS: dict[str, float] = {
    "rising": 1.15,
    "stable": 1.00,
    "declining": 0.82,
}


def compute_environment_factors(
    environment: dict[str, Any],
    strategy_type: str = "",
) -> dict[str, Any]:
    """Compute environment multipliers from configuration.

    Args:
        environment: EnvironmentConfig dict (season, competition_level, etc.).
        strategy_type: Used as a hint for seasonality lookup.

    Returns:
        EnvironmentFactors dict with all computed multipliers.
    """
    try:
        env = copy.deepcopy(environment)

        season = str(env.get("season", "")).lower()
        competition_level = _clamp(float(env.get("competition_level", 0.5)), 0.0, 1.0)
        demand_trend = str(env.get("demand_trend", "stable")).lower()
        market_volatility = _clamp(float(env.get("market_volatility", 0.15)), 0.0, 1.0)
        store_maturity = str(env.get("store_maturity", "growing")).lower()

        seasonality_multiplier = _compute_seasonality(season, strategy_type)
        competition_pressure = _compute_competition_pressure(competition_level)
        demand_elasticity = _compute_demand_elasticity(demand_trend)
        volatility_factor = _compute_volatility(market_volatility)
        maturity_modifier = _MATURITY_MODIFIERS.get(store_maturity, 0.90)

        # Combined modifier is the product of all individual factors
        combined = (
            seasonality_multiplier
            * competition_pressure
            * demand_elasticity
            * maturity_modifier
        )

        return {
            "status": "success",
            "factors": {
                "seasonality_multiplier": round(seasonality_multiplier, 4),
                "competition_pressure": round(competition_pressure, 4),
                "demand_elasticity": round(demand_elasticity, 4),
                "volatility_factor": round(volatility_factor, 4),
                "maturity_modifier": round(maturity_modifier, 4),
                "combined_modifier": round(combined, 4),
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "factors": _default_factors(),
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal computations
# ---------------------------------------------------------------------------

def _compute_seasonality(season: str, strategy_type: str) -> float:
    """Look up seasonality multiplier, falling back to default."""
    season_map = _SEASON_MULTIPLIERS.get(season, {})
    # Try strategy_type as category hint first, then default
    if strategy_type and strategy_type in season_map:
        return season_map[strategy_type]
    return season_map.get("default", 1.0)


def _compute_competition_pressure(level: float) -> float:
    """Higher competition = lower effective demand. Maps 0-1 to 1.1-0.65."""
    return round(1.1 - 0.45 * level, 4)


def _compute_demand_elasticity(trend: str) -> float:
    """Map demand trend string to a multiplier."""
    return _DEMAND_TREND_MODIFIERS.get(trend, 1.0)


def _compute_volatility(raw: float) -> float:
    """Return volatility as a standard-deviation-like factor (0.05 – 0.50)."""
    return round(0.05 + raw * 0.45, 4)


def _default_factors() -> dict[str, float]:
    return {
        "seasonality_multiplier": 1.0,
        "competition_pressure": 1.0,
        "demand_elasticity": 1.0,
        "volatility_factor": 0.15,
        "maturity_modifier": 1.0,
        "combined_modifier": 1.0,
    }


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))
