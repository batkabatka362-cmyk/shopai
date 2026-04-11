"""Conversion domain knowledge — expert heuristics and insights.

What experienced e-commerce operators know about conversion:
  - "Cold traffic converts 1-3%, warm traffic 5-10%, email 15-25%"
  - "Every $10 increase above $50 loses ~5% conversion"
  - "10 reviews = 2x conversion vs 0 reviews"
  - "Free shipping threshold above AOV increases cart size 15%"
  - "Mobile converts 50% lower than desktop but is 70% of traffic"
"""
from __future__ import annotations

from typing import Any


# Expert conversion insights by topic area
CONVERSION_INSIGHTS = {
    "traffic_temperature": {
        "insight": "Cold traffic (paid ads to strangers) converts 1-3%. "
                   "Warm traffic (retargeting, followers) converts 5-10%. "
                   "Email list converts 15-25%. Focus on warming up traffic before selling.",
        "actionable": "Build an email list from day 1. Every subscriber is worth $1-3/month.",
        "priority": "high",
    },
    "price_sensitivity": {
        "insight": "Every $10 increase above $50 loses roughly 5% conversion. "
                   "Below $25 is impulse territory — conversion jumps 40%. "
                   "Above $200, conversion drops 60% and requires extensive social proof.",
        "actionable": "If AOV is high, invest heavily in trust signals and testimonials.",
        "priority": "high",
    },
    "social_proof": {
        "insight": "Products with 10+ reviews convert 2x compared to 0 reviews. "
                   "50+ reviews hit a trust threshold where conversion plateaus. "
                   "Star rating matters more than count — 4.5+ stars is the sweet spot.",
        "actionable": "Get first 10 reviews ASAP. Use post-purchase email flows. "
                      "Offer photo incentives — image reviews convert 3x better.",
        "priority": "critical",
    },
    "cart_abandonment": {
        "insight": "70% of carts are abandoned. Top reason: unexpected costs (48%). "
                   "Second: forced account creation (24%). Third: slow delivery (22%). "
                   "Cart recovery emails recover 5-15% of abandoned carts.",
        "actionable": "Show total cost early. Offer guest checkout. Set up 3-email "
                      "abandoned cart sequence (1hr, 24hr, 72hr).",
        "priority": "critical",
    },
    "mobile_experience": {
        "insight": "Mobile is 70% of traffic but converts 50% lower than desktop. "
                   "Page load time: every 1 second delay loses 7% conversion. "
                   "Thumb-friendly design and one-tap checkout are essential.",
        "actionable": "Test your store on a phone first. Use Shop Pay or Apple Pay. "
                      "Compress images to under 100KB each.",
        "priority": "high",
    },
    "landing_page": {
        "insight": "Dedicated landing pages convert 2-5x better than homepage traffic. "
                   "Above-the-fold hero image + clear CTA = 30% better conversion. "
                   "Video on landing page increases conversion 20-80%.",
        "actionable": "Create specific landing pages for each ad campaign. "
                      "Test hero image vs video. Always have one clear CTA.",
        "priority": "medium",
    },
    "shipping_threshold": {
        "insight": "Free shipping threshold set 15-20% above AOV increases average "
                   "cart size by 15%. 73% of shoppers say free shipping is a "
                   "deciding factor. Flat-rate shipping is better than calculated.",
        "actionable": "Bake shipping into product price and offer 'free shipping'. "
                      "Set free shipping threshold just above your current AOV.",
        "priority": "high",
    },
    "urgency_scarcity": {
        "insight": "Scarcity messaging ('Only 3 left') can increase conversion 5-10% "
                   "but only if authentic. Countdown timers on promotions add 3-8%. "
                   "False urgency erodes trust and increases returns.",
        "actionable": "Use real inventory counts. Run time-limited promotions. "
                      "Never fake scarcity — customers share screenshots.",
        "priority": "medium",
    },
}

# General conversion heuristics
HEURISTICS = [
    "Cold traffic converts 1-3%, warm traffic 5-10%, email 15-25%",
    "Every $10 increase above $50 loses ~5% conversion",
    "10 reviews = 2x conversion vs 0 reviews",
    "70% of carts are abandoned — cart recovery emails save 5-15%",
    "Mobile is 70% of traffic but 50% lower conversion than desktop",
    "Free shipping > 10% discount for conversion (psychologically)",
    "Guest checkout increases conversion 15-30% vs forced registration",
    "Page load: every 1 second delay = 7% conversion loss",
    "Trust badges near checkout button increase conversion 5-10%",
    "Product video increases conversion 20-80% depending on category",
    "3-email abandoned cart sequence recovers 5-15% of lost sales",
    "Charm pricing ($29.99 vs $30) reduces perceived price 15-20%",
]


def get_conversion_insight(topic: str) -> dict[str, Any]:
    """Get expert insight for a specific conversion topic."""
    return CONVERSION_INSIGHTS.get(topic, {
        "insight": "No specific insight available for this topic",
        "actionable": "Focus on the fundamentals: speed, trust, and clarity",
        "priority": "medium",
    })


def get_heuristics() -> list[str]:
    """Get all conversion heuristics."""
    return HEURISTICS


def recommend_improvements(
    current_data: dict[str, Any],
) -> list[dict[str, Any]]:
    """Recommend conversion improvements based on current store data.

    Args:
        current_data: {
            "conversion_rate": float,
            "review_count": int,
            "has_cart_recovery": bool,
            "mobile_optimized": bool,
            "has_free_shipping": bool,
            "traffic_source": str,
        }
    """
    recommendations = []

    if current_data.get("review_count", 0) < 10:
        recommendations.append({
            "action": "Get to 10 reviews — expected 2x conversion boost",
            "impact": "high",
            "effort": "medium",
            "expected_lift_pct": 30,
        })

    if not current_data.get("has_cart_recovery", False):
        recommendations.append({
            "action": "Set up 3-email abandoned cart sequence",
            "impact": "high",
            "effort": "low",
            "expected_lift_pct": 10,
        })

    if not current_data.get("mobile_optimized", False):
        recommendations.append({
            "action": "Optimize mobile experience — 70% of traffic is mobile",
            "impact": "high",
            "effort": "medium",
            "expected_lift_pct": 25,
        })

    if not current_data.get("has_free_shipping", False):
        recommendations.append({
            "action": "Offer free shipping (bake cost into product price)",
            "impact": "medium",
            "effort": "low",
            "expected_lift_pct": 15,
        })

    source = current_data.get("traffic_source", "paid_social")
    if source in ("paid_social", "paid_search"):
        recommendations.append({
            "action": "Build email list to reduce dependence on cold traffic",
            "impact": "high",
            "effort": "high",
            "expected_lift_pct": 40,
        })

    # Sort by impact
    impact_order = {"high": 0, "medium": 1, "low": 2}
    recommendations.sort(key=lambda r: impact_order.get(r["impact"], 1))

    return recommendations
