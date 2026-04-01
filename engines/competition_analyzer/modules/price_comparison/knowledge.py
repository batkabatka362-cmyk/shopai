"""
Price Comparison — Domain Knowledge
=====================================
Encodes pricing strategy wisdom, psychological pricing tactics, and
competitive pricing guidance. This knowledge helps translate raw price
data into strategic recommendations sellers can act on.
"""


# --- Core Pricing Principles ---

PRICING_PRINCIPLES = [
    {
        "id": "price_is_not_only_lever",
        "principle": "Price is NOT the only lever -- compete on value.",
        "detail": (
            "Before lowering price, ask: can I improve packaging, add a bonus "
            "item, offer better images, write better copy, or provide faster "
            "shipping? Each of these can justify the current price."
        ),
    },
    {
        "id": "volume_vs_margin",
        "principle": "Price leaders win on volume, premium wins on margin.",
        "detail": (
            "Low-price strategies require high volume to be profitable. If you "
            "cannot guarantee volume (strong ranking, ads budget), premium "
            "positioning with better margins is often safer for smaller sellers."
        ),
    },
    {
        "id": "perceived_value",
        "principle": "Customers buy perceived value, not objective value.",
        "detail": (
            "A product photographed professionally with clear benefit-driven "
            "copy can command 20-30% more than an identical product with poor "
            "presentation. Invest in listing quality before cutting price."
        ),
    },
    {
        "id": "anchor_effect",
        "principle": "The first price a customer sees becomes their anchor.",
        "detail": (
            "If competitors list at $39.99 and you list at $29.99, customers "
            "perceive a deal. But if you list first at $29.99, that becomes the "
            "anchor and competitors at $39.99 seem overpriced."
        ),
    },
    {
        "id": "price_quality_signal",
        "principle": "Price communicates quality when buyers cannot evaluate directly.",
        "detail": (
            "In categories where quality is hard to assess (supplements, "
            "skincare), pricing too low raises suspicion. Buyers use price "
            "as a proxy for quality and safety."
        ),
    },
    {
        "id": "race_to_bottom",
        "principle": "A race to the bottom has only one winner -- and they barely survive.",
        "detail": (
            "When multiple sellers compete purely on price, margins evaporate. "
            "The winner gets razor-thin profits and the losers exit. Avoid this "
            "trap by differentiating on dimensions other than price."
        ),
    },
]


# --- Pricing Psychology Tactics ---

PRICING_PSYCHOLOGY_TACTICS = [
    {
        "tactic": "charm_pricing",
        "description": "Charm pricing ($X.99) works best in the under-$50 range.",
        "example": "Price at $19.99 instead of $20.00.",
        "effectiveness": "high",
        "best_for": "impulse and casual purchases",
        "avoid_when": "selling luxury or prestige products",
    },
    {
        "tactic": "prestige_pricing",
        "description": "Round numbers ($50.00) signal quality and luxury.",
        "example": "Price at $100.00 instead of $99.99 for premium items.",
        "effectiveness": "high",
        "best_for": "luxury, premium, and gift items",
        "avoid_when": "competing in price-sensitive categories",
    },
    {
        "tactic": "decoy_pricing",
        "description": "Offer three tiers where the middle option looks like the best deal.",
        "example": "Basic $19, Standard $29 (best value), Premium $59.",
        "effectiveness": "moderate",
        "best_for": "products with multiple variants or bundles",
        "avoid_when": "you only have a single SKU",
    },
    {
        "tactic": "bundle_pricing",
        "description": "Combine products to obscure per-unit price comparison.",
        "example": "Sell a 3-pack at $24.99 vs competitor single at $9.99.",
        "effectiveness": "high",
        "best_for": "consumable and commodity products",
        "avoid_when": "customers specifically want single units",
    },
    {
        "tactic": "price_anchoring",
        "description": "Show original or competitor price to make yours look better.",
        "example": "Was $49.99, now $34.99 (30% off).",
        "effectiveness": "high",
        "best_for": "promotional periods and new product launches",
        "avoid_when": "the anchor price is not credible",
    },
    {
        "tactic": "odd_even_pricing",
        "description": "Odd prices ($7, $13) feel calculated; even prices feel curated.",
        "example": "Use $27 for value products, $30 for premium feel.",
        "effectiveness": "low",
        "best_for": "fine-tuning after choosing a price range",
        "avoid_when": "the price difference is negligible",
    },
]


# --- Price Position Strategies ---

PRICE_POSITION_STRATEGIES = {
    "undercut": {
        "when_to_use": [
            "You have a significant cost advantage",
            "You can sustain high volume to compensate for low margin",
            "The category is commoditized with little differentiation",
            "You are a new entrant needing to build review velocity",
        ],
        "risks": [
            "Triggers competitor retaliation",
            "Trains customers to expect low prices",
            "Erodes category profitability for everyone",
        ],
        "max_discount": "20% below median (never more)",
    },
    "match": {
        "when_to_use": [
            "Your product is comparable to competitors",
            "You want to compete on non-price factors",
            "The market is stable without aggressive pricing trends",
            "You have moderate differentiation in listing quality",
        ],
        "risks": [
            "May not stand out in a crowded field",
            "Requires strong non-price differentiation",
        ],
        "target_range": "25th to 75th percentile",
    },
    "premium": {
        "when_to_use": [
            "Your product rating is 4.5+ stars",
            "You have unique features competitors lack",
            "Your brand has recognition and trust",
            "The category supports prestige pricing",
        ],
        "risks": [
            "Lower conversion rate if value is not clearly communicated",
            "Vulnerable to competitors improving quality at lower prices",
        ],
        "min_rating": 4.5,
    },
}


def get_pricing_insight(context):
    """Return the most relevant pricing principle for the given context."""
    context_lower = context.lower() if context else ""
    if "cheap" in context_lower or "low" in context_lower or "undercut" in context_lower:
        return PRICING_PRINCIPLES[5]  # race_to_bottom
    if "premium" in context_lower or "luxury" in context_lower or "high" in context_lower:
        return PRICING_PRINCIPLES[4]  # price_quality_signal
    if "value" in context_lower or "differentiat" in context_lower:
        return PRICING_PRINCIPLES[0]  # price_is_not_only_lever
    if "volume" in context_lower or "margin" in context_lower:
        return PRICING_PRINCIPLES[1]  # volume_vs_margin
    return PRICING_PRINCIPLES[2]  # perceived_value as default


def get_charm_pricing_recommendation(price):
    """Advise whether to use charm pricing based on the price point."""
    if price <= 0:
        return {"use_charm": False, "reason": "Invalid price."}
    if price < 50:
        charm_price = float(int(price)) - 0.01 if price == int(price) else price
        return {
            "use_charm": True,
            "suggested_price": round(int(price + 1) - 0.01, 2) if price > 1 else 0.99,
            "reason": "Under $50, charm pricing increases conversion by 2-8%.",
        }
    return {
        "use_charm": False,
        "suggested_price": round(round(price / 5) * 5, 2),
        "reason": "Above $50, round or prestige pricing signals higher quality.",
    }


def get_competitive_pricing_guidance(position, trend, elasticity):
    """Synthesize a plain-language pricing recommendation."""
    if trend == "decreasing" and elasticity in ("elastic", "moderately_elastic"):
        return (
            "Competitors are lowering prices in a price-sensitive market. "
            "Do not follow them down. Instead, add value through better "
            "images, A+ content, or bundle offers to justify your price."
        )
    if trend == "increasing" and position == "budget":
        return (
            "The market is moving upward but you are priced low. This is an "
            "opportunity to raise prices gradually while competitors climb. "
            "You can capture margin without losing your value positioning."
        )
    if position == "premium" and elasticity == "elastic":
        return (
            "You are priced at a premium in a price-sensitive market. Ensure "
            "your listing clearly communicates why you are worth more. "
            "Consider A/B testing a slightly lower price point."
        )
    if position == "premium" and elasticity in ("inelastic", "veblen"):
        return (
            "Your premium position is well-suited to this market. Buyers here "
            "value quality over price. Maintain your position and invest in "
            "brand-building to strengthen it further."
        )
    return (
        "Your pricing is within a reasonable range. Focus on optimizing your "
        "listing quality, gathering more reviews, and monitoring competitor "
        "moves weekly. Small price adjustments of 3-5% can be tested safely."
    )
