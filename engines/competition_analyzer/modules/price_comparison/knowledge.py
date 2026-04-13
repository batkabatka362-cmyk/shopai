"""
Price Comparison — Domain Knowledge
=====================================
Pricing strategy wisdom, psychological pricing tactics, and competitive
pricing guidance. Translates raw data into strategic recommendations.
"""

PRICING_PRINCIPLES = [
    {"id": "price_is_not_only_lever",
     "principle": "Price is NOT the only lever -- compete on value.",
     "detail": ("Before lowering price, ask: can I improve packaging, add a bonus "
                "item, offer better images, write better copy, or ship faster?")},
    {"id": "volume_vs_margin",
     "principle": "Price leaders win on volume, premium wins on margin.",
     "detail": ("Low-price strategies require high volume. If you cannot guarantee "
                "volume, premium positioning with better margins is safer.")},
    {"id": "perceived_value",
     "principle": "Customers buy perceived value, not objective value.",
     "detail": ("Professional photos and benefit-driven copy can command 20-30% "
                "more than an identical product with poor presentation.")},
    {"id": "anchor_effect",
     "principle": "The first price a customer sees becomes their anchor.",
     "detail": ("If competitors list at $39.99 and you at $29.99, customers perceive "
                "a deal. But if you list first, $29.99 becomes the anchor.")},
    {"id": "price_quality_signal",
     "principle": "Price communicates quality when buyers cannot evaluate directly.",
     "detail": ("In hard-to-assess categories (supplements, skincare), pricing too "
                "low raises suspicion. Buyers use price as a quality proxy.")},
    {"id": "race_to_bottom",
     "principle": "A race to the bottom has only one winner -- and they barely survive.",
     "detail": ("When sellers compete purely on price, margins evaporate. "
                "Differentiate on dimensions other than price.")},
]

PRICING_PSYCHOLOGY_TACTICS = [
    {"tactic": "charm_pricing",
     "description": "Charm pricing ($X.99) works best in the under-$50 range.",
     "example": "$19.99 instead of $20.00.",
     "best_for": "impulse and casual purchases",
     "avoid_when": "selling luxury or prestige products"},
    {"tactic": "prestige_pricing",
     "description": "Round numbers ($50.00) signal quality and luxury.",
     "example": "$100.00 instead of $99.99 for premium items.",
     "best_for": "luxury, premium, and gift items",
     "avoid_when": "competing in price-sensitive categories"},
    {"tactic": "decoy_pricing",
     "description": "Offer three tiers where the middle option looks like the best deal.",
     "example": "Basic $19, Standard $29 (best value), Premium $59.",
     "best_for": "products with multiple variants or bundles",
     "avoid_when": "you only have a single SKU"},
    {"tactic": "bundle_pricing",
     "description": "Combine products to obscure per-unit price comparison.",
     "example": "3-pack at $24.99 vs competitor single at $9.99.",
     "best_for": "consumable and commodity products",
     "avoid_when": "customers specifically want single units"},
    {"tactic": "price_anchoring",
     "description": "Show original or competitor price to make yours look better.",
     "example": "Was $49.99, now $34.99 (30% off).",
     "best_for": "promotional periods and new launches",
     "avoid_when": "the anchor price is not credible"},
    {"tactic": "odd_even_pricing",
     "description": "Odd prices ($7, $13) feel calculated; even prices feel curated.",
     "example": "Use $27 for value, $30 for premium feel.",
     "best_for": "fine-tuning after choosing a price range",
     "avoid_when": "the price difference is negligible"},
]

PRICE_POSITION_STRATEGIES = {
    "undercut": {
        "when_to_use": [
            "You have a significant cost advantage",
            "You can sustain high volume to compensate for low margin",
            "The category is commoditized with little differentiation",
            "You are a new entrant needing review velocity",
        ],
        "risks": ["Triggers competitor retaliation",
                  "Trains customers to expect low prices",
                  "Erodes category profitability"],
        "max_discount": "20% below median (never more)",
    },
    "match": {
        "when_to_use": [
            "Your product is comparable to competitors",
            "You want to compete on non-price factors",
            "The market is stable without aggressive pricing",
            "You have moderate listing quality differentiation",
        ],
        "risks": ["May not stand out in crowded field",
                  "Requires strong non-price differentiation"],
        "target_range": "25th to 75th percentile",
    },
    "premium": {
        "when_to_use": [
            "Your product rating is 4.5+ stars",
            "You have unique features competitors lack",
            "Your brand has recognition and trust",
            "The category supports prestige pricing",
        ],
        "risks": ["Lower conversion if value not communicated",
                  "Vulnerable to quality competitors at lower prices"],
        "min_rating": 4.5,
    },
}


def get_pricing_insight(context):
    """Return the most relevant pricing principle for the given context."""
    c = (context or "").lower()
    if any(w in c for w in ("cheap", "low", "undercut")):
        return PRICING_PRINCIPLES[5]  # race_to_bottom
    if any(w in c for w in ("premium", "luxury", "high")):
        return PRICING_PRINCIPLES[4]  # price_quality_signal
    if any(w in c for w in ("value", "differentiat")):
        return PRICING_PRINCIPLES[0]  # price_is_not_only_lever
    if any(w in c for w in ("volume", "margin")):
        return PRICING_PRINCIPLES[1]  # volume_vs_margin
    return PRICING_PRINCIPLES[2]  # perceived_value


def get_charm_pricing_recommendation(price):
    """Advise whether to use charm pricing based on the price point."""
    if price <= 0:
        return {"use_charm": False, "reason": "Invalid price."}
    if price < 50:
        return {"use_charm": True,
                "suggested_price": round(int(price + 1) - 0.01, 2) if price > 1 else 0.99,
                "reason": "Under $50, charm pricing increases conversion by 2-8%."}
    return {"use_charm": False,
            "suggested_price": round(round(price / 5) * 5, 2),
            "reason": "Above $50, round or prestige pricing signals higher quality."}


def get_competitive_pricing_guidance(position, trend, elasticity):
    """Synthesize a plain-language pricing recommendation."""
    if trend == "decreasing" and elasticity in ("elastic", "moderately_elastic"):
        return ("Competitors are lowering prices in a price-sensitive market. "
                "Do not follow. Add value through better content and bundles.")
    if trend == "increasing" and position == "budget":
        return ("Market is moving up but you are priced low. Raise prices "
                "gradually to capture margin while competitors climb.")
    if position == "premium" and elasticity == "elastic":
        return ("Premium price in a price-sensitive market. Ensure your listing "
                "communicates why you are worth more. Test a lower price point.")
    if position == "premium" and elasticity in ("inelastic", "veblen"):
        return ("Premium position suits this market. Buyers value quality over "
                "price. Maintain position and invest in brand-building.")
    return ("Pricing is within reasonable range. Focus on listing quality, "
            "gathering reviews, and monitoring competitors weekly.")
