"""Differentiation decision logic — ranking, costing, and sustainability.

Decides:
  - Which differentiation strategies are best?
  - What will it cost to implement each strategy?
  - How long before competitors copy and the advantage erodes?
"""
from __future__ import annotations

from typing import Any

from .data import (
    IMPLEMENTATION_COST_RANGES,
    TIME_TO_IMPLEMENT_ESTIMATES,
    SUSTAINABILITY_RATINGS,
)


def rank_differentiation_strategies(
    opportunities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rank strategies by composite score of relevance, cost efficiency, and sustainability.

    Args:
        opportunities: List of strategy dicts, each with relevance_score,
                       cost_level, and sustainability fields.

    Returns:
        Sorted list with composite_rank_score added to each entry.
    """
    for opp in opportunities:
        relevance = opp.get("relevance_score", 50)
        cost_level = opp.get("cost_level", "medium")
        sustainability = opp.get("sustainability", {})

        # Lower cost = higher score bonus
        cost_bonus = {"low": 20, "medium": 10, "high": 0}.get(cost_level, 10)

        # Longer defensibility = higher sustainability bonus
        months = sustainability.get("months_defensible", 6)
        sustain_bonus = min(30, months * 2)

        composite = relevance * 0.5 + cost_bonus + sustain_bonus
        opp["composite_rank_score"] = round(min(100, composite), 1)

    opportunities.sort(key=lambda o: o["composite_rank_score"], reverse=True)

    for rank, opp in enumerate(opportunities, start=1):
        opp["rank"] = rank

    return opportunities


def estimate_differentiation_cost(
    dimension: str, impact_level: str
) -> dict[str, Any]:
    """Estimate cost and time to differentiate on a given dimension.

    Args:
        dimension: One of features, service, brand, content, price.
        impact_level: high, medium, or low.

    Returns:
        Dict with cost_range_usd, time_months, and resource requirements.
    """
    cost_data = IMPLEMENTATION_COST_RANGES.get(dimension, {})
    time_data = TIME_TO_IMPLEMENT_ESTIMATES.get(dimension, {})

    base_cost = cost_data.get(impact_level, cost_data.get("medium", {}))
    base_time = time_data.get(impact_level, time_data.get("medium", 3))

    return {
        "dimension": dimension,
        "impact_level": impact_level,
        "cost_range_usd": base_cost,
        "time_months": base_time,
        "resources_needed": _resources_for_dimension(dimension, impact_level),
        "roi_timeline": _roi_timeline(dimension, impact_level, base_time),
    }


def assess_sustainability(strategy_type: str) -> dict[str, Any]:
    """Assess how long a differentiation strategy remains defensible.

    Some strategies are easy for competitors to copy (features, price).
    Others are inherently hard to replicate (brand story, service culture).

    Args:
        strategy_type: One of better_quality, better_service, niche_focus,
                       brand_story, bundling, customization.

    Returns:
        Sustainability assessment with months_defensible and risk factors.
    """
    rating = SUSTAINABILITY_RATINGS.get(strategy_type, {})
    months = rating.get("months_defensible", 6)
    difficulty = rating.get("copy_difficulty", "medium")
    moat_type = rating.get("moat_type", "none")

    risk_factors = _identify_risk_factors(strategy_type, difficulty)

    if difficulty == "hard":
        sustainability_label = "highly sustainable"
    elif difficulty == "medium":
        sustainability_label = "moderately sustainable"
    else:
        sustainability_label = "easily eroded"

    return {
        "strategy_type": strategy_type,
        "months_defensible": months,
        "copy_difficulty": difficulty,
        "moat_type": moat_type,
        "sustainability_label": sustainability_label,
        "risk_factors": risk_factors,
        "recommendation": _sustainability_recommendation(strategy_type, difficulty),
    }


def _resources_for_dimension(dimension: str, impact_level: str) -> list[str]:
    """Determine what resources are needed for a differentiation effort."""
    base_resources = {
        "features": ["Product development", "Supplier coordination", "Quality testing"],
        "service": ["Customer support team", "Training materials", "CRM tools"],
        "brand": ["Brand strategist", "Designer", "Copywriter"],
        "content": ["Content creator", "Photographer", "SEO specialist"],
        "price": ["Financial analyst", "Supplier negotiation", "Margin modeling"],
    }
    resources = base_resources.get(dimension, ["General resources"])

    if impact_level == "high":
        resources.append("Executive sponsor")
        resources.append("Dedicated project lead")

    return resources


def _roi_timeline(dimension: str, impact_level: str, time_months: int) -> str:
    """Estimate when ROI becomes positive after implementation."""
    roi_months = {
        "features": {"high": 8, "medium": 5, "low": 3},
        "service": {"high": 4, "medium": 3, "low": 2},
        "brand": {"high": 12, "medium": 8, "low": 4},
        "content": {"high": 6, "medium": 4, "low": 2},
        "price": {"high": 3, "medium": 2, "low": 1},
    }
    months_to_roi = roi_months.get(dimension, {}).get(impact_level, 6)
    total = time_months + months_to_roi
    return f"ROI positive within {total} months ({time_months}m build + {months_to_roi}m ramp)"


def _identify_risk_factors(strategy_type: str, difficulty: str) -> list[str]:
    """Identify specific risks that could erode the differentiation."""
    common_risks = {
        "better_quality": [
            "Competitors can source same materials",
            "Quality premium may not justify price increase",
        ],
        "better_service": [
            "Requires ongoing investment in people",
            "Hard to maintain as you scale",
        ],
        "niche_focus": [
            "Niche may be too small for sustainable revenue",
            "Larger player could enter the niche",
        ],
        "brand_story": [
            "Takes time to build — no quick wins",
            "Requires authentic commitment — cannot be faked",
        ],
        "bundling": [
            "Competitors can create their own bundles quickly",
            "Bundle may reduce per-unit margin",
        ],
        "customization": [
            "Operational complexity increases with scale",
            "Higher error rate in fulfillment",
        ],
    }
    risks = common_risks.get(strategy_type, ["General competitive pressure"])

    if difficulty == "easy":
        risks.append("Competitors can replicate within 3-6 months")

    return risks


def _sustainability_recommendation(strategy_type: str, difficulty: str) -> str:
    """Provide a recommendation for maintaining the differentiation."""
    if difficulty == "hard":
        return (
            f"'{strategy_type}' is hard to copy. Double down and make it central "
            f"to your brand identity. Invest consistently."
        )
    elif difficulty == "medium":
        return (
            f"'{strategy_type}' gives moderate protection. Combine with a second "
            f"differentiator to create a layered moat."
        )
    else:
        return (
            f"'{strategy_type}' is easy to copy. Use it for short-term advantage "
            f"but build a harder-to-copy strategy alongside it."
        )
