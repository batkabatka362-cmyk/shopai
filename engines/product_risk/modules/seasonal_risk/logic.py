"""Seasonal Risk — core calculation and strategy logic.

Functions:
  - calculate_cash_reserve_needed: months of cash to survive trough
  - assess_fad_risk: determine if demand is fad vs permanent
  - recommend_seasonal_strategy: actionable strategy per risk level
"""
from __future__ import annotations

from typing import Any

from .data import (
    CASH_RESERVE_REQUIREMENTS,
    FAD_DURATION_BENCHMARKS,
    MONTHLY_DEMAND_INDEX,
)


def calculate_cash_reserve_needed(
    seasonality_profile: dict[str, Any],
    monthly_fixed_costs: float = 5000.0,
    monthly_variable_costs: float = 3000.0,
) -> dict[str, Any]:
    """Calculate the cash reserve required to survive the trough period.

    Uses the peak-to-trough ratio and trough duration to estimate how many
    months of near-zero revenue the business must endure.
    """
    classification = seasonality_profile.get("classification", "non_seasonal")
    requirements = CASH_RESERVE_REQUIREMENTS.get(
        classification, CASH_RESERVE_REQUIREMENTS["non_seasonal"]
    )
    months_needed = requirements["months_reserve"]
    min_ratio = requirements["min_cash_ratio"]

    trough_months = seasonality_profile.get("trough_months", [])
    trough_duration = len(trough_months)
    ptr = seasonality_profile.get("peak_to_trough_ratio", 1.0)

    # During trough, revenue drops to roughly 1/ptr of peak revenue
    trough_revenue_factor = 1.0 / max(ptr, 1.0)
    monthly_burn = monthly_fixed_costs + (monthly_variable_costs * trough_revenue_factor)
    total_reserve = monthly_burn * months_needed

    # Adequacy check: compare reserve requirement to annual revenue fraction
    annual_costs = (monthly_fixed_costs + monthly_variable_costs) * 12
    reserve_ratio = total_reserve / max(annual_costs, 1.0)

    return {
        "classification": classification,
        "months_reserve_needed": months_needed,
        "trough_duration_months": trough_duration,
        "monthly_burn_during_trough": round(monthly_burn, 2),
        "total_reserve_needed": round(total_reserve, 2),
        "min_cash_ratio": min_ratio,
        "reserve_to_annual_cost_ratio": round(reserve_ratio, 3),
        "recommendation": (
            f"Maintain at least ${total_reserve:,.0f} in cash reserves to cover "
            f"{months_needed} months of trough-period expenses."
        ),
    }


def assess_fad_risk(trend_data: dict[str, Any]) -> dict[str, Any]:
    """Assess whether demand signals indicate a fad vs lasting trend.

    Inputs: trend_duration_months, search_volume_trend, repeat_purchase_rate,
            trend_type, social_media_driven.
    """
    duration = trend_data.get("trend_duration_months", 0)
    volume_trend = trend_data.get("search_volume_trend", "stable")
    repeat_rate = trend_data.get("repeat_purchase_rate", 0.0)
    trend_type = trend_data.get("trend_type", "unknown")
    social_driven = trend_data.get("social_media_driven", False)

    fad_score = 0.0  # 0 = permanent, 1 = definite fad

    # Short trend duration is the strongest fad signal
    if duration < 3:
        fad_score += 0.35
    elif duration < 6:
        fad_score += 0.25
    elif duration < 12:
        fad_score += 0.10

    # Explosive growth followed by plateau or decline
    if volume_trend == "spiking":
        fad_score += 0.25
    elif volume_trend == "declining":
        fad_score += 0.20

    # Low repeat purchase = one-time novelty purchase
    if repeat_rate < 0.05:
        fad_score += 0.20
    elif repeat_rate < 0.15:
        fad_score += 0.10

    # Social media driven trends fade faster
    if social_driven:
        fad_score += 0.15

    # Known fad trend types
    benchmark = FAD_DURATION_BENCHMARKS.get(trend_type, {})
    if benchmark:
        fad_score += 0.10

    fad_score = min(fad_score, 1.0)
    is_fad = fad_score >= 0.50
    max_safe_months = benchmark.get("max_months", 6) if is_fad else None

    return {
        "fad_score": round(fad_score, 2),
        "is_fad": is_fad,
        "classification": "fad" if fad_score >= 0.50 else (
            "likely_fad" if fad_score >= 0.35 else "likely_permanent"
        ),
        "max_safe_inventory_months": max_safe_months,
        "exit_urgency": benchmark.get("exit_urgency", "low") if is_fad else "none",
        "signals": {
            "short_trend": duration < 6,
            "volume_spiking_or_declining": volume_trend in ("spiking", "declining"),
            "low_repeat_purchase": repeat_rate < 0.10,
            "social_media_driven": social_driven,
        },
    }


def recommend_seasonal_strategy(
    risk_level: str,
    classification: str = "moderate_seasonal",
    peak_months: list[int] | None = None,
) -> dict[str, Any]:
    """Return an actionable seasonal strategy based on risk classification."""
    peak_months = peak_months or []

    strategies: dict[str, dict[str, Any]] = {
        "non_seasonal": {
            "approach": "steady_state",
            "summary": "Low seasonality risk. Maintain consistent inventory and marketing.",
            "inventory": "Standard reorder cadence; no seasonal pre-builds needed.",
            "cash_flow": "Steady cash flow expected. Standard reserves sufficient.",
            "marketing": "Even marketing spend throughout the year.",
            "launch_timing": "Any month is acceptable for launch.",
        },
        "moderate_seasonal": {
            "approach": "planned_ramp",
            "summary": "Moderate seasonality. Build inventory ahead of peak, taper off after.",
            "inventory": f"Begin inventory build 10-12 weeks before peak (months {peak_months}).",
            "cash_flow": "Build 3-month cash reserve before trough. Budget for lean months.",
            "marketing": "Increase ad spend 4-6 weeks before peak; cut 50% off-peak.",
            "launch_timing": f"Ideal launch: 4-6 weeks before peak months {peak_months}.",
        },
        "highly_seasonal": {
            "approach": "aggressive_cycle",
            "summary": "High seasonality risk. Revenue concentrates in peak; plan for zero-revenue trough.",
            "inventory": f"Full inventory staged 8-12 weeks before peak (months {peak_months}). Liquidate remainders fast.",
            "cash_flow": "4+ months cash reserve mandatory. Pre-negotiate credit lines.",
            "marketing": "80% of annual budget concentrated around peak season.",
            "launch_timing": f"Launch ONLY during ramp-up to peak months {peak_months}.",
        },
        "fad": {
            "approach": "hit_and_run",
            "summary": "Fad product. Maximize short-term extraction and plan exit immediately.",
            "inventory": "Max 2-month inventory commitment. Use dropship or print-on-demand if possible.",
            "cash_flow": "Do not reinvest profits. Hold 50%+ cash ratio against write-offs.",
            "marketing": "Front-load spend. Ride the wave hard for 60-90 days.",
            "launch_timing": "Launch immediately or not at all. Speed is everything.",
        },
    }

    strategy = strategies.get(classification, strategies["moderate_seasonal"])
    strategy["risk_level"] = risk_level
    strategy["classification"] = classification
    return strategy
