"""Market position data — archetypes, thresholds, and positioning examples.

Reference data for evaluating and recommending market positions.
"""
from __future__ import annotations

from typing import Any


# Five core positioning archetypes with detailed characteristics
POSITIONING_ARCHETYPES = {
    "budget_leader": {
        "name": "Budget Leader",
        "description": "Lowest price in the category — win on cost",
        "price_percentile": "bottom 20%",
        "quality_expectation": "acceptable (meets minimum standards)",
        "typical_margin_pct": 15,
        "customer_profile": "Price-sensitive shoppers, bulk buyers, bargain hunters",
        "brand_requirement": "Minimal — price speaks louder than brand",
        "competitive_advantage": "Cost structure and sourcing efficiency",
        "risk": "Race to the bottom — always someone willing to go cheaper",
        "best_for": "Sellers with direct factory relationships or volume discounts",
        "avoid_if": "Your costs don't allow sustainable margins at low prices",
    },
    "value_leader": {
        "name": "Value Leader",
        "description": "Best quality-to-price ratio — win on perceived value",
        "price_percentile": "30th-60th percentile",
        "quality_expectation": "good (exceeds expectations for the price)",
        "typical_margin_pct": 30,
        "customer_profile": "Smart shoppers who compare quality and price",
        "brand_requirement": "Moderate — reviews and social proof matter most",
        "competitive_advantage": "Sweet spot of quality and price that satisfies most buyers",
        "risk": "Squeezed from above (premium drops price) and below (budget improves quality)",
        "best_for": "Most small-to-medium sellers — widest addressable market",
        "avoid_if": "You cannot maintain quality consistency at scale",
    },
    "premium": {
        "name": "Premium",
        "description": "Higher quality and price — win on superiority",
        "price_percentile": "70th-90th percentile",
        "quality_expectation": "excellent (noticeably better than average)",
        "typical_margin_pct": 45,
        "customer_profile": "Quality-conscious buyers willing to pay more for better",
        "brand_requirement": "High — brand trust is essential to justify price",
        "competitive_advantage": "Product quality, brand perception, and customer experience",
        "risk": "Must deliver on premium promise — one bad review hits hard",
        "best_for": "Sellers who can invest in quality, photography, and branding",
        "avoid_if": "You cannot maintain premium across ALL touchpoints",
    },
    "ultra_premium": {
        "name": "Ultra Premium",
        "description": "Highest tier — exclusive, luxury, aspirational",
        "price_percentile": "top 10%",
        "quality_expectation": "exceptional (best in class)",
        "typical_margin_pct": 60,
        "customer_profile": "Affluent buyers, gift purchasers, status-conscious consumers",
        "brand_requirement": "Very high — brand IS the product at this tier",
        "competitive_advantage": "Exclusivity, craftsmanship, brand prestige",
        "risk": "Tiny addressable market — volume is limited",
        "best_for": "Artisans, established brands, sellers with unique sourcing",
        "avoid_if": "You cannot tell a compelling luxury story authentically",
    },
    "niche_specialist": {
        "name": "Niche Specialist",
        "description": "Own a specific sub-segment — win on expertise and focus",
        "price_percentile": "varies (premium within the niche)",
        "quality_expectation": "specialized (perfectly suited for the niche)",
        "typical_margin_pct": 40,
        "customer_profile": "Enthusiasts, professionals, or specific demographic",
        "brand_requirement": "Moderate — expertise and credibility matter more than logo",
        "competitive_advantage": "Deep understanding of niche needs that generalists miss",
        "risk": "Niche may be too small, or a large player may enter",
        "best_for": "Sellers with genuine expertise in a specific domain",
        "avoid_if": "You are choosing niche only because you cannot compete broadly",
    },
}


# Price-quality perception thresholds
PRICE_QUALITY_THRESHOLDS = {
    "budget_ceiling_pct": 30,
    "value_floor_pct": 25,
    "value_ceiling_pct": 65,
    "premium_floor_pct": 60,
    "premium_ceiling_pct": 90,
    "ultra_premium_floor_pct": 85,
    "quality_minimum_for_premium": 70,
    "quality_minimum_for_ultra_premium": 85,
    "quality_minimum_for_value": 55,
    "price_ratio_budget_max": 0.65,
    "price_ratio_premium_min": 1.15,
    "price_ratio_ultra_premium_min": 1.50,
}


# Real-world positioning success examples
SUCCESSFUL_POSITIONING_EXAMPLES = {
    "budget_leader": {
        "example": "Amazon Basics",
        "lesson": (
            "Wins by leveraging massive sourcing power for lowest prices. "
            "Small sellers cannot compete here without unique cost advantages."
        ),
        "key_factor": "Supply chain efficiency",
    },
    "value_leader": {
        "example": "Anker (electronics accessories)",
        "lesson": (
            "Built trust through consistent quality at fair prices. "
            "Reviews became their moat — thousands of 4.5+ star reviews."
        ),
        "key_factor": "Quality consistency and review velocity",
    },
    "premium": {
        "example": "Native (personal care)",
        "lesson": (
            "Premium ingredients + clean brand aesthetic + strong social media "
            "presence justified 3x price over commodity alternatives."
        ),
        "key_factor": "Brand story and ingredient transparency",
    },
    "ultra_premium": {
        "example": "Yeti (coolers and drinkware)",
        "lesson": (
            "Built a cult brand around durability and outdoor lifestyle. "
            "Customers pay 5x commodity price for the brand experience."
        ),
        "key_factor": "Brand community and lifestyle association",
    },
    "niche_specialist": {
        "example": "Bluebonnet Nutrition (supplements for health-conscious consumers)",
        "lesson": (
            "Focused on purity and third-party testing when competitors "
            "competed on price. Owned the 'clean supplements' niche."
        ),
        "key_factor": "Credibility through specialization and certification",
    },
}


def get_archetype(position: str) -> dict[str, Any]:
    """Get the full archetype definition for a position."""
    return POSITIONING_ARCHETYPES.get(position, {
        "name": position,
        "description": "Custom position — define your own characteristics",
        "typical_margin_pct": 30,
        "risk": "Unknown — requires custom analysis",
        "best_for": "Varies",
    })


def get_threshold(key: str) -> float:
    """Get a specific price-quality perception threshold."""
    return PRICE_QUALITY_THRESHOLDS.get(key, 50.0)
