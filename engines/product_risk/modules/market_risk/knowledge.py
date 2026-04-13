"""Market risk domain knowledge — expert insights and battle-tested heuristics.

What a seasoned e-commerce operator knows about market risk:
  - "Saturated markets aren't always bad — find the crack"
  - "Declining markets = stealing share (hard)"
  - "Rising competition + falling prices = death spiral"
"""
from __future__ import annotations

from typing import Any


# Core market risk heuristics — learned from experience
HEURISTICS = [
    "Saturated markets aren't always bad — find the crack. "
    "Every crowded market has underserved segments if you look hard enough.",

    "Declining markets = stealing share (hard). "
    "You're not growing with the tide — you're taking from someone else's plate.",

    "Rising competition + falling prices = death spiral. "
    "When more sellers chase fewer dollars, everyone loses except the customer.",

    "A market with zero competition isn't 'untapped' — it usually doesn't exist. "
    "Validate demand before assuming you found a gold mine.",

    "The best time to enter a market is during the growth phase (2-5 years old). "
    "Too early = unproven. Too late = entrenched incumbents.",

    "Price erosion above 5%/year means your margins shrink every quarter. "
    "You must cut costs faster than prices fall — most can't.",

    "Markets with high barriers to entry are risky to enter but great once you're in. "
    "The same wall that blocks you will block everyone after you.",

    "If the top 3 players hold >60% market share, find a different market. "
    "They have scale advantages you cannot match as a newcomer.",
]

# Risk-specific insights for different market conditions
MARKET_CONDITION_INSIGHTS = {
    "saturated_growing": {
        "condition": "High saturation + growing demand",
        "insight": (
            "The market is crowded BUT still expanding. This is survivable. "
            "Focus on the newest customer segments that incumbents haven't optimized for yet."
        ),
        "strategy": "Target emerging sub-niches within the growing category",
        "example": "Pet wellness in the crowded pet supplies market",
    },
    "saturated_declining": {
        "condition": "High saturation + declining demand",
        "insight": (
            "This is the worst combination. Too many sellers fighting over a shrinking pie. "
            "Margins will compress until players start exiting. Don't be one of them."
        ),
        "strategy": "Avoid entirely unless you can acquire a failing competitor at a discount",
        "example": "Generic phone cases — commoditized and declining",
    },
    "unsaturated_growing": {
        "condition": "Low saturation + growing demand",
        "insight": (
            "The holy grail. Few competitors and rising demand. Move fast — this window "
            "closes as others notice the opportunity."
        ),
        "strategy": "Enter aggressively, build brand before competitors arrive",
        "example": "Sustainable home goods — growing fast, few strong brands",
    },
    "unsaturated_declining": {
        "condition": "Low saturation + declining demand",
        "insight": (
            "Few competitors because the market is dying. Don't confuse 'empty' with "
            "'opportunity'. Others already tried and left."
        ),
        "strategy": "Only enter if you have evidence of a niche revival or seasonal shift",
        "example": "DVD players — few sellers, but demand is gone",
    },
}

# Category-specific risk warnings
CATEGORY_RISK_WARNINGS = {
    "electronics": "Fastest price erosion of any category (~8%/year). "
                   "Your product is worth less every month you hold inventory.",
    "clothing": "Returns run 20-30%. Factor this into your risk calculation. "
                "A 40% margin becomes 25% after returns.",
    "health_beauty": "Regulatory risk is real. One FDA warning letter can shut you down. "
                     "Verify all claims and certifications.",
    "food_beverage": "Shelf life = ticking clock. Unsold inventory becomes waste, not discount stock.",
    "toys_games": "Extremely seasonal — 60% of sales in Q4. "
                  "Cash flow risk is massive during the other 9 months.",
    "pet_supplies": "Lowest risk category overall — recurring purchases, emotional buyers, "
                    "growing market. But Amazon dominates commodity pet products.",
}


def get_market_risk_insights(
    saturation_score: float, demand_score: float
) -> dict[str, Any]:
    """Get contextual insights based on current market conditions.

    Args:
        saturation_score: Saturation risk score 0-100
        demand_score: Demand trend risk score 0-100

    Returns:
        Relevant insight for the market condition combination.
    """
    saturated = saturation_score > 50
    declining = demand_score > 50

    if saturated and declining:
        key = "saturated_declining"
    elif saturated and not declining:
        key = "saturated_growing"
    elif not saturated and declining:
        key = "unsaturated_declining"
    else:
        key = "unsaturated_growing"

    return MARKET_CONDITION_INSIGHTS[key]


def get_heuristics() -> list[str]:
    """Get all market risk heuristics."""
    return HEURISTICS


def get_category_warning(category: str) -> str:
    """Get category-specific risk warning."""
    return CATEGORY_RISK_WARNINGS.get(
        category,
        "No specific category warning available — apply general risk heuristics.",
    )
