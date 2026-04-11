"""Market risk assessment — saturation, demand trends, competitive threats.

Evaluates market-level risks that could undermine product viability:
  - Market saturation: how crowded is the space already?
  - Demand trend: growing, flat, or declining?
  - Competitive intensity: how aggressively are incumbents competing?
  - Price erosion: are prices being driven down?
  - Barrier to entry: how hard is it to enter?
  - Market maturity: where is this market in its lifecycle?

Each dimension scored 0-100 (higher = more risk).
Composite risk score via weighted aggregation.
"""
from __future__ import annotations

from typing import Any

from .data import RISK_THRESHOLDS, MATURITY_RISK_PROFILES


# Weights for composite risk score (must sum to 1.0)
DIMENSION_WEIGHTS = {
    "saturation_level": 0.25,
    "demand_trend_direction": 0.20,
    "competitive_intensity": 0.20,
    "price_erosion_rate": 0.15,
    "barrier_to_entry": 0.10,
    "market_maturity_stage": 0.10,
}

# Risk classification bands
RISK_BANDS = {
    "low": (0, 25),
    "moderate": (25, 50),
    "high": (50, 75),
    "critical": (75, 100),
}


def assess_market_risk(input_payload: dict[str, Any]) -> dict[str, Any]:
    """Assess market-level risks for a product or niche.

    Args:
        input_payload: {
            "category": str,
            "competitor_count": int,
            "search_volume_trend_pct": float,  # e.g. -15 means -15% YoY
            "avg_price_decline_pct": float,     # annual price decline
            "top3_market_share_pct": float,     # combined share of top 3 players
            "requires_certification": bool,
            "market_age_years": int,
        }

    Returns:
        Engine contract: {status, data, meta, error}
    """
    try:
        dimensions = _score_all_dimensions(input_payload)
        composite = _calculate_composite_score(dimensions)
        classification = _classify_risk(composite)
        scenarios = _build_risk_scenarios(dimensions, input_payload)

        return {
            "status": "success",
            "data": {
                "dimensions": dimensions,
                "composite_score": round(composite, 1),
                "classification": classification,
                "risk_scenarios": scenarios,
                "summary": _build_summary(composite, classification, dimensions),
            },
            "meta": {
                "module": "market_risk",
                "version": "1.0",
                "weights": DIMENSION_WEIGHTS,
                "bands": RISK_BANDS,
            },
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "error",
            "data": None,
            "meta": {"module": "market_risk", "version": "1.0"},
            "error": str(exc),
        }


def _score_all_dimensions(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Score each risk dimension 0-100."""
    competitor_count = payload.get("competitor_count", 50)
    trend_pct = payload.get("search_volume_trend_pct", 0)
    price_decline = abs(payload.get("avg_price_decline_pct", 0))
    top3_share = payload.get("top3_market_share_pct", 50)
    requires_cert = payload.get("requires_certification", False)
    market_age = payload.get("market_age_years", 5)

    # Saturation: more competitors = higher risk
    sat_score = min(100, (competitor_count / 500) * 100)

    # Demand trend: declining is risky, growing reduces risk
    if trend_pct <= -20:
        demand_score = 95
    elif trend_pct < 0:
        demand_score = 50 + abs(trend_pct) * 2.25
    elif trend_pct == 0:
        demand_score = 40
    else:
        demand_score = max(0, 40 - trend_pct * 2)

    # Competitive intensity: high top3 share = consolidated, hard to enter
    comp_score = min(100, top3_share * 1.2)

    # Price erosion: prices dropping fast = margin compression
    erosion_score = min(100, price_decline * 5)

    # Barrier to entry: certifications, capital, expertise
    barrier_base = 20
    if requires_cert:
        barrier_base += 35
    if competitor_count < 10:
        barrier_base += 15  # Few competitors may signal high barriers
    barrier_score = min(100, barrier_base + market_age * 2)

    # Market maturity: older markets are harder to disrupt
    maturity_score = _score_maturity(market_age)

    return {
        "saturation_level": {"score": round(sat_score, 1), "detail": f"{competitor_count} competitors identified"},
        "demand_trend_direction": {"score": round(demand_score, 1), "detail": f"{trend_pct:+.1f}% YoY search trend"},
        "competitive_intensity": {"score": round(comp_score, 1), "detail": f"Top 3 hold {top3_share}% share"},
        "price_erosion_rate": {"score": round(erosion_score, 1), "detail": f"{price_decline:.1f}% annual price decline"},
        "barrier_to_entry": {"score": round(barrier_score, 1), "detail": f"Certification required: {requires_cert}"},
        "market_maturity_stage": {"score": round(maturity_score, 1), "detail": f"Market age: ~{market_age} years"},
    }


def _score_maturity(market_age: int) -> float:
    """Score market maturity risk. Young and very old markets are risky differently."""
    if market_age <= 1:
        return 60  # Too new — unproven demand
    if market_age <= 3:
        return 30  # Growth phase — good entry
    if market_age <= 7:
        return 45  # Maturing — moderate risk
    if market_age <= 15:
        return 65  # Mature — incumbents entrenched
    return 80  # Declining/saturated lifecycle


def _calculate_composite_score(dimensions: dict[str, dict[str, Any]]) -> float:
    """Weighted aggregation of all dimension scores."""
    total = 0.0
    for dim_key, weight in DIMENSION_WEIGHTS.items():
        score = dimensions.get(dim_key, {}).get("score", 50)
        total += score * weight
    return total


def _classify_risk(composite: float) -> str:
    """Classify composite risk score into a band."""
    for label, (low, high) in RISK_BANDS.items():
        if low <= composite < high:
            return label
    return "critical"


def _build_risk_scenarios(
    dimensions: dict[str, dict[str, Any]], payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Generate specific risk scenarios with probability and impact."""
    scenarios = []
    sat = dimensions["saturation_level"]["score"]
    demand = dimensions["demand_trend_direction"]["score"]
    erosion = dimensions["price_erosion_rate"]["score"]

    if sat > 60 and erosion > 40:
        scenarios.append({
            "scenario": "Price war triggers margin collapse",
            "probability": "high" if erosion > 60 else "moderate",
            "impact": "severe",
            "description": "Saturated market with declining prices leads to unsustainable margins",
        })
    if demand > 70:
        scenarios.append({
            "scenario": "Demand evaporates within 12 months",
            "probability": "moderate",
            "impact": "critical",
            "description": "Declining search volume accelerates, leaving excess inventory",
        })
    if sat > 50 and demand > 50:
        scenarios.append({
            "scenario": "Death spiral — rising competition meets falling demand",
            "probability": "moderate" if sat < 70 else "high",
            "impact": "critical",
            "description": "Too many sellers chasing shrinking buyer pool",
        })
    if not scenarios:
        scenarios.append({
            "scenario": "Market conditions remain stable",
            "probability": "high",
            "impact": "low",
            "description": "No immediate risk triggers detected",
        })
    return scenarios


def _build_summary(composite: float, classification: str, dimensions: dict) -> str:
    """Human-readable risk summary."""
    worst = max(dimensions.items(), key=lambda x: x[1]["score"])
    return (
        f"Overall market risk: {classification.upper()} ({composite:.0f}/100). "
        f"Highest concern: {worst[0].replace('_', ' ')} at {worst[1]['score']:.0f}/100."
    )
