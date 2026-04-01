"""Saturation domain knowledge — expert strategies for saturated markets.

What veterans know:
  - "Every saturated market has an unsaturated sub-niche"
  - "If everyone's competing on price, compete on experience"
  - "Saturated markets have the most data — use it to find the crack"
  - "The best time to enter a saturated market is NEVER... unless you have THE angle"
"""
from __future__ import annotations

from typing import Any


# Strategies that work in saturated markets
SATURATED_MARKET_STRATEGIES = {
    "brand_moat": {
        "name": "Build a brand, not a product",
        "description": "In commoditized markets, brand IS the differentiation.",
        "playbook": [
            "Create brand story that resonates with target customer",
            "Invest in packaging and unboxing experience",
            "Build community (Facebook group, Instagram, newsletter)",
            "Content marketing: become the authority in your niche",
            "Customer service as competitive advantage",
        ],
        "works_best_when": "You have patience (12+ months) and can tell a compelling story",
        "example": "Gymshark in saturated fitness apparel — community + influencer strategy",
    },
    "sub_niche_dominance": {
        "name": "Dominate a micro-niche",
        "description": "Don't compete in 'yoga mats'. Dominate 'extra-thick yoga mats for bad knees'.",
        "playbook": [
            "Find the long-tail keyword nobody targets",
            "Create product perfectly solving that specific need",
            "Own every piece of content for that keyword",
            "Become THE brand for that micro-niche",
            "Expand to adjacent micro-niches only after dominating first",
        ],
        "works_best_when": "Micro-niche has 1000+ monthly searches and <10 direct competitors",
        "example": "Purple Mattress — didn't compete in 'mattresses', competed in 'pressure-relief mattress'",
    },
    "experience_premium": {
        "name": "Sell the experience, not the product",
        "description": "Same product + better experience = premium pricing.",
        "playbook": [
            "Premium packaging (unboxing videos go viral)",
            "Handwritten thank-you notes",
            "2-day shipping (or faster)",
            "Hassle-free returns (no questions asked)",
            "Follow-up emails with tips on using the product",
        ],
        "works_best_when": "Competitors are faceless/generic and customer values experience",
        "example": "Chewy (pet supplies) — handwritten birthday cards for pets",
    },
    "content_authority": {
        "name": "Become the knowledge source",
        "description": "Create content so good that customers trust you BEFORE buying.",
        "playbook": [
            "YouTube channel with product education/reviews",
            "Blog with SEO-optimized buying guides",
            "Email course teaching customers about the category",
            "Comparison content (your product vs competitors)",
            "UGC (user-generated content) collection and amplification",
        ],
        "works_best_when": "Category has a learning curve or customers research before buying",
        "example": "Beardbrand — saturated grooming market, won via YouTube education",
    },
    "subscription_conversion": {
        "name": "Convert one-time to subscription",
        "description": "If product is consumable, subscription = recurring revenue + defensible moat.",
        "playbook": [
            "Offer subscribe-and-save (10-15% discount)",
            "Auto-replenishment at optimal intervals",
            "Surprise gifts for long-term subscribers",
            "Cancellation flow that offers pause instead of cancel",
            "Subscribers get early access to new products",
        ],
        "works_best_when": "Product is consumable (supplements, coffee, pet food, skincare)",
        "example": "Dollar Shave Club — saturated razor market, won via subscription model",
    },
}

# Warning signs that you're entering a death trap
DEATH_TRAP_SIGNS = [
    {
        "sign": "Average selling price declining >10%/year",
        "meaning": "Sellers destroying each other on price. No one profits.",
        "action": "AVOID unless you can maintain price through brand.",
    },
    {
        "sign": "Top 10 sellers have <3.5 star average AND low prices",
        "meaning": "Race to bottom on both quality and price. Nobody invests in product.",
        "action": "AVOID — cheap sellers will always undercut you.",
    },
    {
        "sign": "50%+ of competitors launched in last 6 months",
        "meaning": "Everyone saw the same 'trending product' video. Hype-driven rush.",
        "action": "AVOID — most will fail but they'll crash prices first.",
    },
    {
        "sign": "Multiple patent/trademark lawsuits in the category",
        "meaning": "Legal minefield. IP issues.",
        "action": "AVOID or get legal review first.",
    },
    {
        "sign": "Amazon private label already in category",
        "meaning": "Amazon Basics will undercut everyone. Hard to compete.",
        "action": "AVOID commodity versions. Focus on premium/specialized.",
    },
]

# Market lifecycle positions
LIFECYCLE_POSITIONS = {
    "early_market": {
        "saturation_range": (0, 20),
        "typical_duration": "6-18 months",
        "best_strategy": "Speed to market. Establish presence before others arrive.",
        "risk": "Market may not materialize. Demand unproven.",
    },
    "growth_market": {
        "saturation_range": (20, 45),
        "typical_duration": "12-36 months",
        "best_strategy": "Quality execution. Build reviews and brand. Capture market share.",
        "risk": "Competition increasing. Need to establish position quickly.",
    },
    "mature_market": {
        "saturation_range": (45, 70),
        "typical_duration": "Indefinite",
        "best_strategy": "Differentiation or niche focus. Brand and loyalty matter most.",
        "risk": "Hard to gain market share. Marketing costs high.",
    },
    "oversaturated_market": {
        "saturation_range": (70, 100),
        "typical_duration": "Until shakeout",
        "best_strategy": "Sub-niche domination or exit. Don't compete head-on.",
        "risk": "Margin destruction. Race to bottom. High failure rate.",
    },
}


def get_saturated_strategies() -> dict[str, Any]:
    """Get all strategies for entering saturated markets."""
    return SATURATED_MARKET_STRATEGIES


def get_death_trap_signs() -> list[dict[str, Any]]:
    """Get warning signs of market death traps."""
    return DEATH_TRAP_SIGNS


def get_lifecycle_position(saturation_index: int) -> dict[str, Any]:
    """Get market lifecycle position based on saturation."""
    for name, config in LIFECYCLE_POSITIONS.items():
        low, high = config["saturation_range"]
        if low <= saturation_index < high:
            return {"position": name, **config}
    return {"position": "oversaturated_market", **LIFECYCLE_POSITIONS["oversaturated_market"]}


def recommend_strategy_for_level(saturation_level: str) -> list[str]:
    """Recommend strategies based on saturation level."""
    recommendations = {
        "unsaturated": ["first_mover"],
        "lightly_saturated": ["content_authority", "brand_moat"],
        "moderately_saturated": ["sub_niche_dominance", "experience_premium", "content_authority"],
        "highly_saturated": ["sub_niche_dominance", "subscription_conversion", "brand_moat"],
        "oversaturated": ["sub_niche_dominance"],
    }
    strategy_names = recommendations.get(saturation_level, ["sub_niche_dominance"])
    return [SATURATED_MARKET_STRATEGIES[s]["name"] for s in strategy_names if s in SATURATED_MARKET_STRATEGIES]
