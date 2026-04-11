"""Decision functions for legal risk management.

Provides actionable guidance: what certifications are needed, liability
exposure estimates, and IP risk checks for specific products.
"""

from __future__ import annotations

from typing import Any

from .data import (
    get_regulatory_requirements,
    get_compliance_cost,
    get_liability_tier,
    COMPLIANCE_COST_RANGES,
    COMMON_IP_PITFALLS,
    LIABILITY_INSURANCE_RATES,
)


def recommend_legal_path(risks: dict[str, Any]) -> dict[str, Any]:
    """Recommend certifications and legal steps based on assessed risks.

    Args:
        risks: the 'data' dict from assess_legal_risk result.

    Returns:
        Engine contract {status, data, meta, error}.
    """
    if not risks or "dimensions" not in risks:
        return _error("Invalid risks — pass the 'data' field from assess_legal_risk")

    dimensions = risks["dimensions"]
    steps: list[dict[str, Any]] = []
    priority_order = 1

    # Regulatory compliance path
    if dimensions.get("regulatory_compliance", 0) >= 30:
        for req in risks.get("legal_requirements", []):
            steps.append({
                "priority": priority_order,
                "action": f"Obtain: {req}",
                "category": "regulatory",
                "urgency": "before_launch",
                "estimated_weeks": 4,
            })
            priority_order += 1

    # IP clearance path
    if dimensions.get("ip_infringement", 0) >= 25:
        steps.append({
            "priority": priority_order,
            "action": "Conduct professional patent and trademark clearance search",
            "category": "ip_protection",
            "urgency": "before_sourcing",
            "estimated_weeks": 3,
            "cost_range": COMPLIANCE_COST_RANGES["patent_search"],
        })
        priority_order += 1
        steps.append({
            "priority": priority_order,
            "action": "Register your brand trademark with USPTO",
            "category": "ip_protection",
            "urgency": "within_3_months",
            "estimated_weeks": 12,
            "cost_range": COMPLIANCE_COST_RANGES["trademark_registration"],
        })
        priority_order += 1

    # Liability insurance path
    if dimensions.get("product_liability", 0) >= 30:
        steps.append({
            "priority": priority_order,
            "action": "Obtain product liability insurance policy",
            "category": "liability",
            "urgency": "before_launch",
            "estimated_weeks": 2,
            "cost_range": {"low": risks["liability_insurance_annual"]["low"],
                           "high": risks["liability_insurance_annual"]["high"]},
        })
        priority_order += 1

    # Advertising compliance path
    if dimensions.get("advertising_claims", 0) >= 30:
        steps.append({
            "priority": priority_order,
            "action": "Review all marketing claims with FTC guidelines; remove unsubstantiated claims",
            "category": "advertising",
            "urgency": "before_launch",
            "estimated_weeks": 2,
        })
        priority_order += 1

    # Platform compliance path
    if risks.get("platform_issues"):
        for issue in risks["platform_issues"]:
            steps.append({
                "priority": priority_order,
                "action": f"Resolve platform issue — {issue}",
                "category": "platform",
                "urgency": "before_listing",
                "estimated_weeks": 3,
            })
            priority_order += 1

    total_cost = risks.get("estimated_compliance_cost", {"low": 0, "high": 0})
    total_weeks = sum(s.get("estimated_weeks", 0) for s in steps)

    return {
        "status": "success",
        "data": {
            "steps": steps,
            "total_steps": len(steps),
            "estimated_total_cost": total_cost,
            "estimated_total_weeks": total_weeks,
            "critical_path": [s for s in steps if s["urgency"] == "before_launch"],
        },
        "meta": {"risk_level": risks.get("risk_level", "unknown")},
        "error": None,
    }


def estimate_liability_exposure(product_type: str) -> dict[str, Any]:
    """Estimate product liability exposure for a given product type.

    Args:
        product_type: product category string.

    Returns:
        Engine contract with liability analysis.
    """
    tier = get_liability_tier(product_type)
    insurance_info = LIABILITY_INSURANCE_RATES.get(tier, LIABILITY_INSURANCE_RATES["medium_risk"])
    premium = insurance_info["annual_premium"]
    coverage = insurance_info["coverage"]

    # Estimate lawsuit probability and cost
    lawsuit_prob_map = {
        "low_risk": 0.001, "medium_risk": 0.005,
        "high_risk": 0.015, "very_high_risk": 0.03,
    }
    avg_settlement_map = {
        "low_risk": 15000, "medium_risk": 50000,
        "high_risk": 150000, "very_high_risk": 500000,
    }
    lawsuit_prob = lawsuit_prob_map.get(tier, 0.005)
    avg_settlement = avg_settlement_map.get(tier, 50000)
    expected_annual_cost = round(lawsuit_prob * avg_settlement, 2)

    insurance_recommended = expected_annual_cost > premium[0] * 0.5

    return {
        "status": "success",
        "data": {
            "liability_tier": tier,
            "annual_premium_range": {"low": premium[0], "high": premium[1]},
            "coverage_amount": coverage,
            "lawsuit_probability_annual": lawsuit_prob,
            "average_settlement": avg_settlement,
            "expected_annual_liability_cost": expected_annual_cost,
            "insurance_recommended": insurance_recommended,
            "recommendation": (
                f"Product liability insurance at ${premium[0]}-${premium[1]}/year is "
                f"{'strongly recommended' if insurance_recommended else 'optional but prudent'} "
                f"for {tier.replace('_', ' ')} products"
            ),
        },
        "meta": {"product_type": product_type, "tier": tier},
        "error": None,
    }


def check_ip_risk(product_name: str, category: str) -> dict[str, Any]:
    """Check IP infringement risk for a specific product.

    Args:
        product_name: the product name or title.
        category: product category string.

    Returns:
        Engine contract with IP risk analysis.
    """
    flags: list[dict[str, Any]] = []
    risk_score = 10

    # Check category-specific pitfalls
    for pitfall in COMMON_IP_PITFALLS:
        if pitfall["category"] == category or pitfall["category"] in category:
            freq_scores = {"very_high": 25, "high": 18, "medium": 10, "low": 5}
            risk_score += freq_scores.get(pitfall["frequency"], 8)
            flags.append({
                "type": pitfall["risk"],
                "detail": pitfall["detail"],
                "frequency": pitfall["frequency"],
            })

    # Check product name for trademark risks
    name_lower = product_name.lower()
    trademarked_terms = {
        "bluetooth": "Bluetooth SIG trademark — requires licensing",
        "wifi": "Wi-Fi Alliance trademark — requires certification",
        "velcro": "VELCRO is a registered trademark — use 'hook and loop'",
        "band-aid": "BAND-AID is a registered trademark — use 'adhesive bandage'",
        "jacuzzi": "JACUZZI is a registered trademark — use 'hot tub'",
    }
    for term, warning in trademarked_terms.items():
        if term in name_lower:
            risk_score += 15
            flags.append({"type": "trademark_term", "detail": warning, "frequency": "certain"})

    risk_level = "low" if risk_score < 25 else ("moderate" if risk_score < 50 else "high")

    actions = ["Conduct USPTO trademark search before finalizing brand/product name"]
    if risk_score >= 30:
        actions.append("Engage a patent attorney for a freedom-to-operate analysis")
    if risk_score >= 50:
        actions.append("Consider design-around strategies to avoid known patents")
        actions.append("Budget $3K-$8K for professional IP clearance")

    return {
        "status": "success",
        "data": {
            "ip_risk_score": min(risk_score, 100),
            "risk_level": risk_level,
            "flags": flags,
            "recommended_actions": actions,
            "estimated_clearance_cost": COMPLIANCE_COST_RANGES["patent_search"],
        },
        "meta": {"product_name": product_name, "category": category},
        "error": None,
    }


def _error(message: str) -> dict[str, Any]:
    """Return a standardized error response."""
    return {
        "status": "error",
        "data": None,
        "meta": {},
        "error": message,
    }
