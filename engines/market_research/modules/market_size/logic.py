"""Market size decision logic — should we enter this market?

Takes TAM/SAM/SOM calculations and produces actionable decisions:
- Is this market worth entering?
- What store maturity level is needed?
- What's the minimum viable scale?
"""
from __future__ import annotations

from typing import Any


# Decision thresholds
THRESHOLDS = {
    "minimum_monthly_som": 5000,       # Below $5K/month → too small
    "attractive_monthly_som": 20000,    # $20K+/month → attractive
    "excellent_monthly_som": 100000,    # $100K+/month → excellent
    "minimum_tam_for_growth": 1_000_000_000,  # $1B TAM → room to grow
    "max_niche_pct_for_safety": 0.5,   # If niche is >50% of category → risky
}


def decide_market_entry(market_size: dict[str, Any]) -> dict[str, Any]:
    """Decide whether to enter a market based on size analysis.

    Args:
        market_size: Output from code.full_market_size()

    Returns:
        Decision with verdict, score, and reasoning.
    """
    tam = market_size.get("tam", {})
    sam = market_size.get("sam", {})
    som = market_size.get("som", {})

    annual_tam = tam.get("annual_tam_usd", 0)
    monthly_som_typical = som.get("monthly_som_usd", {}).get("typical", 0)
    monthly_som_max = som.get("monthly_som_usd", {}).get("max", 0)
    sub_niche_pct = tam.get("sub_niche_pct", 0.1)

    # Score calculation (0-100)
    score = 0
    reasons = []
    warnings = []

    # SOM score (0-40 points)
    if monthly_som_typical >= THRESHOLDS["excellent_monthly_som"]:
        score += 40
        reasons.append(f"Excellent SOM: ${monthly_som_typical:,}/month potential")
    elif monthly_som_typical >= THRESHOLDS["attractive_monthly_som"]:
        score += 30
        reasons.append(f"Attractive SOM: ${monthly_som_typical:,}/month potential")
    elif monthly_som_typical >= THRESHOLDS["minimum_monthly_som"]:
        score += 15
        reasons.append(f"Moderate SOM: ${monthly_som_typical:,}/month — viable but tight")
    else:
        score += 5
        warnings.append(f"Low SOM: ${monthly_som_typical:,}/month — may not cover costs")

    # TAM growth room (0-25 points)
    if annual_tam >= THRESHOLDS["minimum_tam_for_growth"]:
        score += 25
        reasons.append(f"Large TAM (${annual_tam/1e9:.1f}B) — room to grow")
    elif annual_tam >= 100_000_000:
        score += 15
        reasons.append(f"Moderate TAM (${annual_tam/1e6:.0f}M)")
    else:
        score += 5
        warnings.append(f"Small TAM (${annual_tam/1e6:.0f}M) — limited growth ceiling")

    # Niche concentration risk (0-20 points)
    if sub_niche_pct <= 0.1:
        score += 20
        reasons.append("Well-defined niche within large category — good positioning")
    elif sub_niche_pct <= THRESHOLDS["max_niche_pct_for_safety"]:
        score += 10
        reasons.append("Moderate niche size — reasonable focus")
    else:
        score += 5
        warnings.append("Very broad niche — harder to differentiate")

    # Upside potential (0-15 points)
    if monthly_som_max > monthly_som_typical * 3:
        score += 15
        reasons.append(f"High upside: up to ${monthly_som_max:,}/month with strong execution")
    elif monthly_som_max > monthly_som_typical * 2:
        score += 10
    else:
        score += 5

    # Verdict
    if score >= 75:
        verdict = "strong_enter"
        recommendation = "Enter this market — strong opportunity"
    elif score >= 55:
        verdict = "enter"
        recommendation = "Enter with focused strategy — good opportunity"
    elif score >= 35:
        verdict = "cautious"
        recommendation = "Consider carefully — moderate opportunity, execution must be excellent"
    else:
        verdict = "avoid"
        recommendation = "Avoid or find a more specific niche — too small or too competitive"

    return {
        "verdict": verdict,
        "score": min(100, score),
        "recommendation": recommendation,
        "reasons": reasons,
        "warnings": warnings,
        "thresholds_used": THRESHOLDS,
    }


def required_scale(market_size: dict[str, Any], target_monthly_revenue: float = 10000) -> dict[str, Any]:
    """Calculate what's needed to reach target revenue in this market.

    Returns required conversion rate, traffic, ad spend estimates.
    """
    som = market_size.get("som", {})
    monthly_som_typical = som.get("monthly_som_usd", {}).get("typical", 0)

    if monthly_som_typical <= 0:
        return {"status": "insufficient_data"}

    # What % of SOM do we need to capture?
    required_capture = target_monthly_revenue / max(monthly_som_typical, 1)

    # Traffic estimates (assuming 2% conversion rate)
    conversion_rate = 0.02
    avg_order_value = 50  # Default assumption
    orders_needed = target_monthly_revenue / avg_order_value
    traffic_needed = orders_needed / conversion_rate

    # Ad spend estimates ($1-3 CPC average)
    estimated_cpc = 1.50
    organic_traffic_pct = 0.30  # 30% organic after 6 months
    paid_traffic = traffic_needed * (1 - organic_traffic_pct)
    monthly_ad_spend = paid_traffic * estimated_cpc

    return {
        "target_monthly_revenue": target_monthly_revenue,
        "required_som_capture_pct": round(required_capture * 100, 2),
        "feasible": required_capture <= 1.0,
        "traffic_needed": round(traffic_needed),
        "orders_needed": round(orders_needed),
        "estimated_monthly_ad_spend": round(monthly_ad_spend),
        "assumptions": {
            "conversion_rate": conversion_rate,
            "avg_order_value": avg_order_value,
            "cpc": estimated_cpc,
            "organic_pct": organic_traffic_pct,
        },
    }
