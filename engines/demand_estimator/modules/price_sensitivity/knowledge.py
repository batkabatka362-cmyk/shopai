"""Price sensitivity domain knowledge — expert pricing heuristics.

What experienced e-commerce pricing strategists know:
  - "Elasticity <1 means raise prices — demand barely drops"
  - "Elasticity >2 means compete on value, not price"
  - "Charm pricing ($X.99) reduces perceived price by 15-20%"
  - "Anchoring (show original price) increases conversions 10-30%"
  - "Bundle pricing captures 15-25% more revenue per transaction"
"""
from __future__ import annotations

from typing import Any


# Expert pricing insights by topic
PRICING_INSIGHTS = {
    "elasticity_strategy": {
        "insight": "If elasticity is less than 1 (inelastic), raise prices — demand barely "
                   "drops and revenue grows. If elasticity exceeds 2, you're in a price war "
                   "zone — compete on value, brand, and experience instead.",
        "actionable": "Calculate your category elasticity. Inelastic? Test a 10% price increase. "
                      "Elastic? Invest in differentiation before touching price.",
        "priority": "critical",
    },
    "psychological_pricing": {
        "insight": "Charm pricing ($X.99) reduces perceived price by 15-20%. "
                   "Left-digit effect: $29.99 feels significantly cheaper than $30.00. "
                   "However, round numbers ($50, $100) signal quality for premium products.",
        "actionable": "Use .99 pricing for value products, round numbers for premium. "
                      "Test both — the 'right' approach depends on your brand positioning.",
        "priority": "medium",
    },
    "anchoring": {
        "insight": "Showing a higher 'was' price (anchoring) increases purchase rate by "
                   "10-30%. The anchor should be 2-3x the sale price for maximum effect. "
                   "Compare-at pricing works even when customers know it's a tactic.",
        "actionable": "Always show compare-at price. Use MSRP as anchor if available. "
                      "Never anchor more than 3x — it destroys credibility.",
        "priority": "high",
    },
    "bundling": {
        "insight": "Product bundles capture 15-25% more revenue per transaction. "
                   "Sweet spot is 15% bundle discount — enough to motivate but preserves margin. "
                   "Bundles also reduce comparison shopping (harder to price-compare bundles).",
        "actionable": "Create 2-3 product bundles with 10-20% discount. "
                      "Name them descriptively ('Starter Kit', 'Complete Set').",
        "priority": "high",
    },
    "competitor_response": {
        "insight": "In commodity markets, competitors match price cuts within 1-3 days — "
                   "price wars destroy everyone's margins. In differentiated markets, "
                   "you can maintain 20-50% premium without losing meaningful share.",
        "actionable": "Measure your differentiation honestly. If customers can't articulate "
                      "why you're different, you're a commodity — don't cut price, differentiate.",
        "priority": "high",
    },
    "price_testing": {
        "insight": "Sequential price tests are unreliable — external factors confound results. "
                   "A/B split testing is the only valid method. Need 1000+ visitors per variant "
                   "and 7+ days minimum. Test price AND value proposition together.",
        "actionable": "Run simultaneous A/B tests with clear success metrics. "
                      "Test 2 prices max at a time. Run for at least 2 weeks.",
        "priority": "medium",
    },
    "subscription_pricing": {
        "insight": "Subscription pricing reduces effective per-unit price sensitivity by 30-50%. "
                   "Customers evaluate monthly cost, not per-item cost. "
                   "Subscribe-and-save with 10-15% discount has 60% uptake rate.",
        "actionable": "If your product is consumable, offer subscribe-and-save. "
                      "Start with 10% discount — increase only if uptake is below 20%.",
        "priority": "medium",
    },
    "price_perception": {
        "insight": "Free shipping is perceived as more valuable than an equivalent discount. "
                   "'$30 + free shipping' outsells '$25 + $5 shipping' despite identical total. "
                   "Shipping costs are the #1 reason for cart abandonment (48% of cases).",
        "actionable": "Bake shipping into product price. Show 'FREE SHIPPING' prominently. "
                      "If margins are tight, set a free shipping threshold above AOV.",
        "priority": "high",
    },
}

# General pricing heuristics
HEURISTICS = [
    "Elasticity <1 = raise prices (demand barely drops)",
    "Elasticity >2 = compete on value not price",
    "Charm pricing ($X.99) reduces perceived price 15-20%",
    "Anchoring with 'was' price increases conversion 10-30%",
    "Bundle discount sweet spot is 15% — enough to motivate, preserves margin",
    "Never race to bottom on price — it's a war nobody wins",
    "Free shipping beats equivalent dollar discount every time",
    "Round prices ($50, $100) signal premium quality",
    "Price increases of 5-10% often go unnoticed by customers",
    "Subscribe-and-save reduces price sensitivity 30-50%",
    "Test prices with A/B splits, never sequential changes",
    "If you can't defend a premium price, you don't have a brand — you have a commodity",
]


def get_pricing_insight(topic: str) -> dict[str, Any]:
    """Get expert insight for a specific pricing topic."""
    return PRICING_INSIGHTS.get(topic, {
        "insight": "No specific insight available for this topic",
        "actionable": "Focus on understanding your category elasticity before making changes",
        "priority": "medium",
    })


def get_heuristics() -> list[str]:
    """Get all pricing heuristics."""
    return HEURISTICS


def recommend_pricing_strategy(
    current_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Recommend pricing strategy based on current product/store data.

    Args:
        current_data: {
            "elasticity": float,
            "current_margin_pct": float,
            "competitor_price_ratio": float,  # our_price / competitor_avg
            "has_subscription": bool,
            "brand_strength": float,  # 0-1
            "category": str,
        }
    """
    recommendations = []
    elasticity = abs(current_data.get("elasticity", 1.0))
    margin = current_data.get("current_margin_pct", 30)
    price_ratio = current_data.get("competitor_price_ratio", 1.0)
    brand = current_data.get("brand_strength", 0.3)

    if elasticity < 0.8 and margin < 50:
        recommendations.append({
            "action": "Raise prices 10-15% — inelastic demand means minimal volume loss",
            "impact": "high",
            "effort": "low",
            "expected_revenue_lift_pct": 8,
        })

    if elasticity > 1.5 and price_ratio > 1.1:
        recommendations.append({
            "action": "Price is above market for an elastic category — lower or differentiate",
            "impact": "high",
            "effort": "medium",
            "expected_revenue_lift_pct": 15,
        })

    if not current_data.get("has_subscription", False) and elasticity < 1.2:
        recommendations.append({
            "action": "Add subscribe-and-save option with 10% discount",
            "impact": "medium",
            "effort": "medium",
            "expected_revenue_lift_pct": 12,
        })

    if brand < 0.4 and price_ratio > 1.2:
        recommendations.append({
            "action": "Weak brand with premium pricing — invest in brand or lower price",
            "impact": "high",
            "effort": "high",
            "expected_revenue_lift_pct": 20,
        })

    if margin > 60:
        recommendations.append({
            "action": "High margins allow promotional flexibility — test bundle pricing",
            "impact": "medium",
            "effort": "low",
            "expected_revenue_lift_pct": 10,
        })

    # Sort by impact
    impact_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda r: impact_order.get(r["impact"], 1))

    return recommendations
