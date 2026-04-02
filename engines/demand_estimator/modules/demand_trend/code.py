"""Demand trend analysis engine — is demand growing, stable, or declining?

Analyzes demand signals over time to determine:
  - Trend direction: growing / stable / declining / seasonal
  - Trend velocity: how fast is demand changing?
  - Inflection points: is the trend accelerating or decelerating?
  - Year-over-year comparison
  - Forward forecast: where will demand be in 3/6/12 months?
"""
from __future__ import annotations

from typing import Any

from .data import (
    TREND_VELOCITY_BENCHMARKS,
    SEASONAL_ADJUSTMENT_FACTORS,
    get_velocity_benchmark,
)


def analyze_demand_trend(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Analyze demand trend from historical signal data.

    Args:
        input_payload: {
            "monthly_demand": list[float],       # Monthly demand values, newest last
            "prior_year_demand": list[float] | None,  # Same months from prior year
            "category": str,
            "signal_type": str,                  # "search_volume" | "sales" | "interest"
        }

    Returns:
        Engine contract: {status, data, meta, error}
    """
    try:
        monthly_demand = input_payload["monthly_demand"]
        prior_year = input_payload.get("prior_year_demand")
        category = input_payload.get("category", "general")
        signal_type = input_payload.get("signal_type", "search_volume")

        if len(monthly_demand) < 2:
            return {
                "status": "error",
                "data": None,
                "meta": None,
                "error": "Need at least 2 months of demand data for trend analysis",
            }

        # Step 1: Determine trend direction
        direction = _classify_trend_direction(monthly_demand, category)

        # Step 2: Calculate trend velocity
        velocity = _calculate_trend_velocity(monthly_demand)

        # Step 3: Detect inflection points
        inflection = _detect_inflection_points(monthly_demand)

        # Step 4: Year-over-year comparison
        yoy = _year_over_year_comparison(monthly_demand, prior_year)

        # Step 5: Forward forecast (3/6/12 months)
        forecast = _forecast_demand(monthly_demand, velocity, category)

        # Step 6: Classify velocity against benchmarks
        velocity_class = _classify_velocity(velocity["monthly_pct_change"], category)

        return {
            "status": "ok",
            "data": {
                "direction": direction,
                "velocity": velocity,
                "velocity_classification": velocity_class,
                "inflection": inflection,
                "year_over_year": yoy,
                "forecast": forecast,
            },
            "meta": {
                "data_points": len(monthly_demand),
                "category": category,
                "signal_type": signal_type,
                "oldest_value": monthly_demand[0],
                "newest_value": monthly_demand[-1],
            },
            "error": None,
        }

    except KeyError as exc:
        return {
            "status": "error",
            "data": None,
            "meta": None,
            "error": f"Missing required field: {exc}",
        }
    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": None,
            "error": f"Demand trend analysis failed: {exc}",
        }


def _classify_trend_direction(
    demand: list[float], category: str
) -> dict[str, Any]:
    """Classify overall trend direction from demand history."""
    if len(demand) < 2:
        return {"direction": "insufficient_data", "confidence": 0.0}

    # Calculate simple linear slope across all data points
    n = len(demand)
    x_mean = (n - 1) / 2.0
    y_mean = sum(demand) / n
    numerator = sum((i - x_mean) * (d - y_mean) for i, d in enumerate(demand))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    slope = numerator / max(denominator, 0.001)

    # Normalize slope as percentage of mean
    slope_pct = (slope / max(y_mean, 0.001)) * 100

    # Check for seasonality (high variance around the trend)
    residuals = [abs(d - (y_mean + slope * (i - x_mean))) for i, d in enumerate(demand)]
    avg_residual_pct = (sum(residuals) / n) / max(y_mean, 0.001) * 100

    # Classify
    if avg_residual_pct > 25 and abs(slope_pct) < 5:
        direction = "seasonal"
        confidence = min(0.95, avg_residual_pct / 40)
    elif slope_pct > 3:
        direction = "growing"
        confidence = min(0.95, slope_pct / 15)
    elif slope_pct < -3:
        direction = "declining"
        confidence = min(0.95, abs(slope_pct) / 15)
    else:
        direction = "stable"
        confidence = min(0.95, 1.0 - abs(slope_pct) / 5)

    return {
        "direction": direction,
        "confidence": round(confidence, 2),
        "slope_pct_per_month": round(slope_pct, 2),
        "description": _direction_description(direction, slope_pct),
    }


def _calculate_trend_velocity(demand: list[float]) -> dict[str, Any]:
    """Calculate how fast demand is changing."""
    if len(demand) < 2:
        return {"monthly_pct_change": 0.0, "absolute_change": 0.0}

    # Recent velocity (last 3 months if available)
    recent = demand[-3:] if len(demand) >= 3 else demand
    first_val = recent[0] if recent[0] > 0 else 0.01
    last_val = recent[-1]

    total_change = last_val - first_val
    pct_change = (total_change / first_val) * 100
    periods = max(len(recent) - 1, 1)
    monthly_pct = pct_change / periods

    # Overall velocity (full history)
    overall_first = demand[0] if demand[0] > 0 else 0.01
    overall_pct = ((demand[-1] - demand[0]) / overall_first) * 100
    overall_monthly = overall_pct / max(len(demand) - 1, 1)

    return {
        "monthly_pct_change": round(monthly_pct, 2),
        "recent_pct_change": round(pct_change, 2),
        "overall_monthly_pct_change": round(overall_monthly, 2),
        "absolute_change_per_month": round(total_change / periods, 1),
        "accelerating": monthly_pct > overall_monthly,
    }


def _detect_inflection_points(demand: list[float]) -> dict[str, Any]:
    """Detect whether the trend is accelerating, decelerating, or inflecting."""
    if len(demand) < 4:
        return {"type": "insufficient_data", "details": "Need 4+ data points"}

    mid = len(demand) // 2
    first_half = demand[:mid]
    second_half = demand[mid:]

    first_change = (first_half[-1] - first_half[0]) / max(len(first_half) - 1, 1)
    second_change = (second_half[-1] - second_half[0]) / max(len(second_half) - 1, 1)

    if second_change > first_change + 0.5:
        inflection_type = "accelerating"
        description = "Demand growth is speeding up"
    elif second_change < first_change - 0.5:
        inflection_type = "decelerating"
        description = "Demand growth is slowing down"
    elif first_change < 0 and second_change > 0:
        inflection_type = "recovery"
        description = "Demand was declining but is now recovering"
    elif first_change > 0 and second_change < 0:
        inflection_type = "peak_passed"
        description = "Demand was growing but has started declining"
    else:
        inflection_type = "steady"
        description = "Demand trend is consistent"

    return {
        "type": inflection_type,
        "description": description,
        "first_half_rate": round(first_change, 2),
        "second_half_rate": round(second_change, 2),
    }


def _year_over_year_comparison(
    current: list[float], prior_year: list[float] | None
) -> dict[str, Any]:
    """Compare current demand to same period last year."""
    if not prior_year or len(prior_year) == 0:
        return {"available": False, "reason": "No prior year data provided"}

    # Compare overlapping months
    overlap = min(len(current), len(prior_year))
    current_period = current[-overlap:]
    prior_period = prior_year[-overlap:]

    current_avg = sum(current_period) / overlap
    prior_avg = sum(prior_period) / overlap

    if prior_avg <= 0:
        return {"available": False, "reason": "Prior year values are zero"}

    yoy_change_pct = ((current_avg - prior_avg) / prior_avg) * 100

    return {
        "available": True,
        "yoy_change_pct": round(yoy_change_pct, 1),
        "current_avg": round(current_avg, 1),
        "prior_year_avg": round(prior_avg, 1),
        "months_compared": overlap,
        "interpretation": _interpret_yoy(yoy_change_pct),
    }


def _forecast_demand(
    demand: list[float], velocity: dict[str, Any], category: str
) -> dict[str, Any]:
    """Forecast demand at 3, 6, and 12 months out."""
    current = demand[-1]
    monthly_pct = velocity.get("monthly_pct_change", 0) / 100

    # Dampen growth rate for longer forecasts (mean reversion)
    forecasts = {}
    for horizon, months in [("3_months", 3), ("6_months", 6), ("12_months", 12)]:
        dampened_rate = monthly_pct * (0.9 ** months)  # Growth decays over time
        projected = current * ((1 + dampened_rate) ** months)
        projected = max(0, projected)  # Floor at zero
        forecasts[horizon] = {
            "projected_value": round(projected, 1),
            "change_from_current_pct": round(((projected - current) / max(current, 0.01)) * 100, 1),
            "dampened_monthly_rate": round(dampened_rate * 100, 2),
        }

    return forecasts


def _classify_velocity(monthly_pct: float, category: str) -> dict[str, str]:
    """Classify trend velocity against benchmarks."""
    benchmarks = get_velocity_benchmark(category)
    if monthly_pct >= benchmarks["rapid_growth"]:
        return {"class": "rapid_growth", "label": "Rapid growth — hot market"}
    if monthly_pct >= benchmarks["moderate_growth"]:
        return {"class": "moderate_growth", "label": "Healthy growth — good market"}
    if monthly_pct >= benchmarks["slow_growth"]:
        return {"class": "slow_growth", "label": "Slow growth — mature market"}
    if monthly_pct >= benchmarks["declining"]:
        return {"class": "stable", "label": "Stable — flat demand"}
    return {"class": "declining", "label": "Declining — shrinking market"}


def _direction_description(direction: str, slope_pct: float) -> str:
    """Human-readable trend direction description."""
    descriptions = {
        "growing": f"Demand is growing at ~{abs(slope_pct):.1f}%/month",
        "declining": f"Demand is declining at ~{abs(slope_pct):.1f}%/month",
        "stable": "Demand is roughly stable with minor fluctuations",
        "seasonal": "Demand shows seasonal patterns — analyze by quarter, not month",
    }
    return descriptions.get(direction, "Trend direction unclear")


def _interpret_yoy(yoy_pct: float) -> str:
    """Interpret year-over-year change."""
    if yoy_pct > 20:
        return "Strong growth — market is expanding rapidly"
    if yoy_pct > 5:
        return "Healthy growth — market is expanding"
    if yoy_pct > -5:
        return "Flat — market is mature/stable"
    if yoy_pct > -15:
        return "Declining — market is contracting"
    return "Steep decline — market may be dying or shifting to alternatives"
