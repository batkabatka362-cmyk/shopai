"""Market risk decision logic — top risks, mitigation, risk-adjusted opportunity.

Takes risk assessment output and produces actionable recommendations:
  - Which risks matter most?
  - What specific actions reduce each risk?
  - How does risk discount the raw opportunity score?
"""
from __future__ import annotations

from typing import Any


# Mitigation strategies mapped to risk dimensions
MITIGATION_STRATEGIES = {
    "saturation_level": [
        "Differentiate on brand story, not price — saturated markets punish commodity sellers",
        "Target an underserved micro-niche within the broader saturated market",
        "Build a proprietary product or bundle that competitors cannot easily replicate",
    ],
    "demand_trend_direction": [
        "Validate demand with a small test campaign before committing inventory",
        "Pivot to adjacent categories where demand is growing",
        "Focus on stealing share from weak competitors rather than growing the pie",
    ],
    "competitive_intensity": [
        "Avoid head-to-head competition with dominant players — find their blind spot",
        "Invest in organic SEO and content marketing to reduce dependence on paid ads",
        "Build direct customer relationships (email, community) to reduce platform risk",
    ],
    "price_erosion_rate": [
        "Add value through bundling, customization, or premium packaging to justify price",
        "Lock in supplier costs with longer-term agreements to protect margins",
        "Shift to subscription or recurring revenue model to stabilize income",
    ],
    "barrier_to_entry": [
        "Use high barriers as a moat — if you get in, others cannot follow easily",
        "Partner with established players for certifications and compliance",
        "Start with lower-barrier product variants while building toward certified ones",
    ],
    "market_maturity_stage": [
        "In mature markets, compete on customer experience and service, not product features",
        "Look for technology shifts that could reset the market (e.g., new materials, D2C)",
        "Consider adjacent emerging markets that leverage your mature-market expertise",
    ],
}


def identify_top_risks(
    assessment: dict[str, Any], top_n: int = 3
) -> list[dict[str, Any]]:
    """Identify the top N risks by severity from an assessment.

    Args:
        assessment: Output from code.assess_market_risk()["data"]
        top_n: Number of top risks to return (default 3)

    Returns:
        List of top risks sorted by score (highest first).
    """
    dimensions = assessment.get("dimensions", {})
    ranked = sorted(
        dimensions.items(),
        key=lambda item: item[1].get("score", 0),
        reverse=True,
    )

    top_risks = []
    for dim_key, dim_data in ranked[:top_n]:
        score = dim_data.get("score", 0)
        if score >= 75:
            severity = "critical"
        elif score >= 50:
            severity = "high"
        elif score >= 25:
            severity = "moderate"
        else:
            severity = "low"

        top_risks.append({
            "dimension": dim_key,
            "score": score,
            "severity": severity,
            "detail": dim_data.get("detail", ""),
            "rank": len(top_risks) + 1,
        })

    return top_risks


def recommend_risk_mitigation(
    risks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate specific mitigation actions for each identified risk.

    Args:
        risks: Output from identify_top_risks()

    Returns:
        List of risks with attached mitigation strategies.
    """
    recommendations = []
    for risk in risks:
        dim = risk.get("dimension", "")
        score = risk.get("score", 0)
        strategies = MITIGATION_STRATEGIES.get(dim, [])

        # Pick the most relevant strategy based on severity
        if score >= 75 and len(strategies) >= 1:
            primary = strategies[0]
            secondary = strategies[1] if len(strategies) > 1 else None
        elif score >= 50 and len(strategies) >= 2:
            primary = strategies[1]
            secondary = strategies[2] if len(strategies) > 2 else None
        elif strategies:
            primary = strategies[-1]
            secondary = None
        else:
            primary = "Conduct deeper research into this specific risk factor"
            secondary = None

        entry = {
            "dimension": dim,
            "score": score,
            "severity": risk.get("severity", "unknown"),
            "primary_action": primary,
            "secondary_action": secondary,
            "urgency": "immediate" if score >= 75 else "short_term" if score >= 50 else "monitor",
        }
        recommendations.append(entry)

    return recommendations


def calculate_risk_adjusted_opportunity(
    opportunity_score: float,
    risk_score: float,
    risk_tolerance: float = 0.5,
) -> dict[str, Any]:
    """Discount an opportunity score by the assessed risk.

    Higher risk = larger discount on the opportunity.
    Risk tolerance controls how aggressively risk discounts opportunity:
      - 0.0 = very conservative (risk heavily penalizes opportunity)
      - 0.5 = balanced (default)
      - 1.0 = aggressive (risk barely affects opportunity)

    Args:
        opportunity_score: Raw opportunity score 0-100
        risk_score: Composite market risk score 0-100
        risk_tolerance: How much risk to tolerate (0-1)

    Returns:
        Risk-adjusted opportunity with interpretation.
    """
    tolerance_clamped = max(0.0, min(1.0, risk_tolerance))

    # Discount factor: at risk=100, conservative gets 0.1x, aggressive gets 0.7x
    min_multiplier = 0.1 + tolerance_clamped * 0.6  # 0.1 to 0.7
    discount = 1.0 - (risk_score / 100) * (1.0 - min_multiplier)
    adjusted = opportunity_score * discount

    # Determine if the risk-adjusted opportunity is still viable
    if adjusted >= 60:
        verdict = "proceed"
        interpretation = "Opportunity remains strong even after accounting for risk"
    elif adjusted >= 40:
        verdict = "proceed_with_caution"
        interpretation = "Opportunity is moderate after risk adjustment — mitigate top risks first"
    elif adjusted >= 20:
        verdict = "risky"
        interpretation = "Risk significantly erodes the opportunity — only proceed with strong mitigations"
    else:
        verdict = "avoid"
        interpretation = "Risk-adjusted opportunity is too low — look for better alternatives"

    return {
        "raw_opportunity_score": opportunity_score,
        "risk_score": risk_score,
        "risk_tolerance": tolerance_clamped,
        "discount_factor": round(discount, 3),
        "adjusted_opportunity_score": round(adjusted, 1),
        "verdict": verdict,
        "interpretation": interpretation,
    }
