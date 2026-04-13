"""Demand trend decision logic — trajectory prediction and sustainability assessment.

Takes trend analysis and produces actionable decisions:
  - Where will demand be in N months? (trajectory prediction)
  - Is there a ceiling on demand? (ceiling detection)
  - Is this demand sustainable or a flash-in-the-pan? (sustainability scoring)
"""
from __future__ import annotations

from typing import Any

from .data import (
    DEMAND_CEILING_INDICATORS,
    CATEGORY_LIFECYCLE_POSITIONS,
    get_lifecycle_position,
)


def predict_demand_trajectory(
    trend_data: dict[str, Any], months: int = 12
) -> list[dict[str, Any]]:
    """Predict demand trajectory over N months.

    Uses current velocity with dampening for longer horizons.
    Factors in category lifecycle position for ceiling effects.

    Args:
        trend_data: {
            "current_demand": float,
            "monthly_pct_change": float,       # Recent monthly growth rate (%)
            "direction": str,                  # growing / stable / declining / seasonal
            "category": str,
        }
        months: Number of months to project forward
    """
    current = trend_data.get("current_demand", 0)
    monthly_rate = trend_data.get("monthly_pct_change", 0) / 100
    direction = trend_data.get("direction", "stable")
    category = trend_data.get("category", "general")

    lifecycle = get_lifecycle_position(category)
    ceiling_factor = lifecycle.get("growth_ceiling_factor", 1.0)

    trajectory = []
    demand = current

    for month in range(1, months + 1):
        # Dampen rate over time (mean reversion toward 0)
        dampening = 0.92 ** month
        effective_rate = monthly_rate * dampening

        # Apply category ceiling — growth slows as you approach ceiling
        if direction == "growing" and ceiling_factor < 1.0:
            effective_rate *= ceiling_factor

        # Seasonal oscillation for seasonal trends
        if direction == "seasonal":
            seasonal_wave = 0.15 * _seasonal_sine(month)
            effective_rate += seasonal_wave

        demand = demand * (1 + effective_rate)
        demand = max(0, demand)

        trajectory.append({
            "month": month,
            "projected_demand": round(demand, 1),
            "effective_growth_rate_pct": round(effective_rate * 100, 2),
            "cumulative_change_pct": round(((demand - current) / max(current, 0.01)) * 100, 1),
        })

    return trajectory


def detect_demand_ceiling(historical: list[float]) -> dict[str, Any]:
    """Detect whether demand is approaching a ceiling.

    A ceiling exists when:
      - Growth rate is decelerating over 3+ months
      - Absolute values are plateauing (variance decreasing)
      - Category lifecycle suggests maturity

    Args:
        historical: Monthly demand values, newest last (at least 4 months)
    """
    if len(historical) < 4:
        return {
            "ceiling_detected": False,
            "confidence": 0.0,
            "reason": "Insufficient data — need 4+ months",
        }

    # Check for decelerating growth
    growth_rates = []
    for i in range(1, len(historical)):
        prev = historical[i - 1] if historical[i - 1] > 0 else 0.01
        rate = (historical[i] - historical[i - 1]) / prev
        growth_rates.append(rate)

    # Is growth slowing? Compare first half rates to second half
    mid = len(growth_rates) // 2
    first_half_avg = sum(growth_rates[:mid]) / max(mid, 1)
    second_half_avg = sum(growth_rates[mid:]) / max(len(growth_rates) - mid, 1)

    deceleration = first_half_avg - second_half_avg

    # Check for plateau (low recent variance)
    recent = historical[-4:]
    recent_mean = sum(recent) / len(recent)
    recent_variance_pct = (
        sum(abs(v - recent_mean) for v in recent) / len(recent)
    ) / max(recent_mean, 0.01) * 100

    # Scoring
    ceiling_score = 0
    indicators = []

    if deceleration > 0.02:
        ceiling_score += 40
        indicators.append(f"Growth decelerating: {first_half_avg:.1%}/mo -> {second_half_avg:.1%}/mo")

    if recent_variance_pct < 8:
        ceiling_score += 30
        indicators.append(f"Recent demand plateauing (variance {recent_variance_pct:.1f}%)")

    if second_half_avg < 0.01:
        ceiling_score += 20
        indicators.append("Recent growth near zero")

    ceiling_detected = ceiling_score >= 50

    return {
        "ceiling_detected": ceiling_detected,
        "confidence": round(min(ceiling_score / 100, 0.95), 2),
        "indicators": indicators,
        "estimated_ceiling_value": round(max(historical[-3:]), 1) if ceiling_detected else None,
        "deceleration_rate": round(deceleration * 100, 2),
        "recent_variance_pct": round(recent_variance_pct, 1),
    }


def assess_demand_sustainability(signals: dict[str, Any]) -> dict[str, Any]:
    """Assess whether current demand is sustainable or a temporary spike.

    Evaluates multiple signals to determine demand quality:
      - Is it driven by a trend or fundamental need?
      - Is growth organic or paid/viral?
      - How broad is the demand base?

    Args:
        signals: {
            "trend_direction": str,          # growing / stable / declining / seasonal
            "trend_age_months": int,         # How long has this trend existed?
            "yoy_change_pct": float | None,  # Year-over-year change
            "search_volume_trend": str,      # growing / stable / declining
            "category": str,
            "is_fad_risk": bool | None,      # Is this a potential fad product?
        }
    """
    direction = signals.get("trend_direction", "stable")
    trend_age = signals.get("trend_age_months", 0)
    yoy_change = signals.get("yoy_change_pct")
    search_trend = signals.get("search_volume_trend", "stable")
    category = signals.get("category", "general")
    is_fad_risk = signals.get("is_fad_risk", False)

    lifecycle = get_lifecycle_position(category)

    score = 0
    reasons = []
    risks = []

    # Trend longevity (longer = more sustainable)
    if trend_age >= 12:
        score += 30
        reasons.append(f"Trend has persisted {trend_age} months — likely sustainable")
    elif trend_age >= 6:
        score += 20
        reasons.append(f"Trend is {trend_age} months old — gaining stability")
    elif trend_age >= 3:
        score += 10
        reasons.append(f"Trend is only {trend_age} months old — still early")
    else:
        score += 5
        risks.append("Very new trend (<3 months) — could be temporary")

    # Direction alignment
    if direction == "growing" and search_trend == "growing":
        score += 25
        reasons.append("Both sales and search demand are growing — strong signal")
    elif direction == "stable":
        score += 20
        reasons.append("Stable demand — mature and predictable")
    elif direction == "declining":
        score += 5
        risks.append("Declining demand — swimming against the current")

    # Year-over-year validation
    if yoy_change is not None:
        if yoy_change > 10:
            score += 20
            reasons.append(f"Strong YoY growth ({yoy_change:+.1f}%) validates demand")
        elif yoy_change > 0:
            score += 15
            reasons.append(f"Positive YoY ({yoy_change:+.1f}%) — demand holding up")
        elif yoy_change > -10:
            score += 10
            risks.append(f"Flat/slight YoY decline ({yoy_change:+.1f}%)")
        else:
            score += 0
            risks.append(f"Significant YoY decline ({yoy_change:+.1f}%) — demand eroding")

    # Category lifecycle
    if lifecycle["stage"] in ("growth", "early_growth"):
        score += 15
        reasons.append(f"Category in {lifecycle['stage']} phase — tailwind")
    elif lifecycle["stage"] == "mature":
        score += 10
    elif lifecycle["stage"] == "declining":
        score += 0
        risks.append("Category is in decline — headwind for all products")

    # Fad risk
    if is_fad_risk:
        score -= 15
        risks.append("Product may be a fad — demand could evaporate quickly")

    score = max(0, min(100, score))

    if score >= 70:
        verdict = "sustainable"
        recommendation = "Demand is likely sustainable — safe to invest"
    elif score >= 45:
        verdict = "moderately_sustainable"
        recommendation = "Demand is probably sustainable but monitor closely"
    else:
        verdict = "risky"
        recommendation = "Demand sustainability is questionable — keep investment small"

    return {
        "sustainability_score": score,
        "verdict": verdict,
        "recommendation": recommendation,
        "reasons": reasons,
        "risks": risks,
        "category_lifecycle": lifecycle["stage"],
    }


def _seasonal_sine(month: int) -> float:
    """Simple seasonal oscillation for demand modeling."""
    import math
    # Peak in month 11-12 (holiday), trough in month 1-2 (post-holiday)
    return math.sin((month - 3) * math.pi / 6)
