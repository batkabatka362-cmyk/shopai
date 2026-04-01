"""Marketplace trends domain knowledge — expert intelligence on bestseller analysis.

What experienced marketplace sellers know:
  - "BSR is a lagging indicator — by the time you see it, the smart money moved"
  - "Never compete head-on with a product that has 5000+ reviews"
  - "Cross-marketplace confirmation is the strongest demand signal"
  - "The money is in the accessories, not the hero product"
  - "Amazon BSR resets every 24 hours — one day means nothing"
"""
from __future__ import annotations

from typing import Any


MARKETPLACE_HEURISTICS: list[str] = [
    "BSR under 1000 sustained for 7+ days = real demand, not a promotion spike",
    "BSR drops 50%+ overnight = likely a Lightning Deal or coupon — wait for normalization",
    "Product appearing on Amazon AND Etsy trending = genuine consumer demand, not platform-specific",
    "Products with < 50 reviews in Top 100 BSR = new market with low review moat — best entry window",
    "If top 5 BSR products all have < 4.0 stars, there is a quality gap you can exploit",
    "Price point $18-$45 is the sweet spot — enough margin for FBA fees + PPC while staying impulse-buy range",
    "Ignore BSR in categories you can't source within 30 days — the window will close",
    "Track BSR at the same time daily — Amazon updates ranks with a ~2 hour lag from purchases",
    "Shopify trending stores with consistent Similarweb traffic growth > 30% MoM = validated DTC winner",
    "Etsy trending + high 'favorited' count = strong gift-giving potential — plan for Q4 surge",
    "Products that trend on TikTok Shop AND Amazon simultaneously are the highest-confidence signals",
    "Never stock more than 60 days of inventory on a trending product — demand can evaporate quickly",
    "Amazon 'Movers & Shakers' page (biggest BSR gains in 24h) is noisy — use 7-day BSR trends instead",
    "A product with BSR #500 in Toys in November will be BSR #50000 in February — always check seasonality",
]

ADJACENT_PRODUCT_STRATEGIES: dict[str, dict[str, Any]] = {
    "accessory_play": {
        "description": "Sell accessories and add-ons for confirmed bestsellers",
        "when_to_use": "Bestseller has strong review moat (1000+ reviews) you can't beat",
        "margin_potential": "40-70% — accessories have lower COGS and less competition",
        "examples": [
            "Phone case accessories for bestselling phone model",
            "Replacement filters for trending air purifier",
            "Carrying case for popular portable electronics",
            "Custom stands/mounts for trending gadgets",
        ],
        "risk_level": "low",
        "time_to_market": "2-4 weeks with existing supplier relationships",
    },
    "bundle_differentiation": {
        "description": "Create bundles that combine the category product with complementary items",
        "when_to_use": "Category has many similar single-item listings with similar BSR",
        "margin_potential": "35-55% — higher AOV justifies higher ad spend",
        "examples": [
            "Yoga mat + blocks + strap bundle vs individual mat listings",
            "Kitchen knife + sharpener + cutting board set",
            "Skincare starter kit combining trending individual products",
        ],
        "risk_level": "medium",
        "time_to_market": "3-6 weeks to source and package",
    },
    "quality_upgrade": {
        "description": "Launch a premium version when incumbent bestsellers have quality complaints",
        "when_to_use": "Top BSR products have < 4.2 average rating with recurring complaints",
        "margin_potential": "45-65% — premium pricing with better materials",
        "examples": [
            "Stainless steel version of plastic bestseller",
            "Organic/natural version of chemical-based product",
            "Heavy-duty version of flimsy trending item",
        ],
        "risk_level": "medium",
        "time_to_market": "4-8 weeks for product development and sampling",
    },
    "niche_targeting": {
        "description": "Take the bestseller concept but target a specific underserved niche",
        "when_to_use": "Bestseller is generic — specific audience segments are underserved",
        "margin_potential": "35-50% — smaller market but less competition",
        "examples": [
            "Left-handed version of popular kitchen tool",
            "Travel-sized version of bestselling home product",
            "Pet-safe version of popular household item",
            "Kids version of trending adult product",
        ],
        "risk_level": "low-medium",
        "time_to_market": "3-6 weeks",
    },
}

BSR_INTERPRETATION_GUIDE: dict[str, str] = {
    "rapid_rise": "BSR improved 50%+ in < 7 days — could be organic demand or promotion. "
                  "Check if price dropped recently or if a coupon is active.",
    "steady_climb": "BSR improving 10-30% per week over 3+ weeks — strongest signal of "
                    "genuine growing demand. Prioritize entry.",
    "plateau": "BSR stable within 20% range for 30+ days — established product. "
               "Hard to displace unless you differentiate significantly.",
    "volatile": "BSR swinging 50%+ between data points — unreliable demand pattern. "
                "Could be inventory issues, promotion cycles, or seasonal.",
    "decline": "BSR worsening over 2+ weeks — demand fading. Do NOT enter this market "
               "unless you have strong evidence the decline is temporary.",
}


def get_marketplace_heuristics() -> list[str]:
    """Return expert heuristics for interpreting marketplace trend data."""
    return MARKETPLACE_HEURISTICS


def get_adjacent_product_strategy(strategy_type: str = "") -> dict[str, Any]:
    """Get a specific adjacent product strategy or all strategies.

    Args:
        strategy_type: One of accessory_play, bundle_differentiation,
                       quality_upgrade, niche_targeting. Empty returns all.
    """
    if strategy_type and strategy_type in ADJACENT_PRODUCT_STRATEGIES:
        return ADJACENT_PRODUCT_STRATEGIES[strategy_type]
    return {
        "strategies": ADJACENT_PRODUCT_STRATEGIES,
        "recommendation": (
            "Start with accessory_play (lowest risk), then graduate to "
            "bundle_differentiation or quality_upgrade once you validate demand."
        ),
    }


def interpret_bsr_pattern(pattern: str) -> str:
    """Return expert interpretation of a BSR movement pattern."""
    return BSR_INTERPRETATION_GUIDE.get(
        pattern, "Unknown pattern — collect more BSR data points before acting."
    )
