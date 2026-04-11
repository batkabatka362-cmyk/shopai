"""Supplier risk domain knowledge — battle-tested insights from sourcing veterans.

What experienced e-commerce operators know about supplier risk:
  - "Chinese New Year = 6 weeks disruption every year"
  - "Single supplier = single point of failure"
  - "Always have Plan B supplier identified before you need it"
"""
from __future__ import annotations

from typing import Any


# Core supplier risk heuristics — learned from painful experience
HEURISTICS = [
    "Chinese New Year = 6 weeks disruption every year. "
    "Plan your orders 2 months ahead or face empty shelves in February.",

    "Single supplier = single point of failure. "
    "It's not a question of IF they'll let you down, but WHEN.",

    "Always have Plan B supplier identified before you need it. "
    "Finding a backup during a crisis means paying triple and accepting worse quality.",

    "The cheapest supplier is rarely the cheapest in the long run. "
    "Factor in defects, delays, returns, and customer service costs.",

    "Visit your supplier (or hire an inspector) at least once before placing a large order. "
    "Alibaba photos lie. Factory conditions tell the truth.",

    "A supplier who can't reply within 48 hours before they have your money "
    "won't reply within a week after they have it.",

    "Trading companies add 15-30% markup over factory prices. "
    "They're useful for small orders but cut them out at scale.",

    "Never pay 100% upfront. Standard terms: 30% deposit, 70% before shipping. "
    "Your leverage disappears the moment all money is transferred.",
]

# Seasonal disruption calendar for supplier planning
SEASONAL_DISRUPTIONS = {
    "chinese_new_year": {
        "timing": "Late January to mid-February (varies)",
        "duration_weeks": 4,
        "affected_countries": ["china", "taiwan", "vietnam"],
        "impact": (
            "Factories shut down 2-4 weeks. Workers may not return for 6 weeks. "
            "Place orders by November to receive before CNY. "
            "Post-CNY production doesn't normalize until March."
        ),
        "action": "Order 3 months of stock before CNY. Plan Q1 inventory in October.",
    },
    "golden_week": {
        "timing": "October 1-7 (China)",
        "duration_weeks": 1,
        "affected_countries": ["china"],
        "impact": (
            "One week shutdown but can extend with surrounding weekends. "
            "Less severe than CNY but still causes delays."
        ),
        "action": "Avoid orders that would land during Golden Week. Ship before or after.",
    },
    "ramadan": {
        "timing": "Varies (lunar calendar), typically March-May",
        "duration_weeks": 4,
        "affected_countries": ["turkey", "bangladesh", "indonesia"],
        "impact": (
            "Productivity drops 30-40% during fasting hours. "
            "Factories may reduce shifts. Expect 1-2 week delays."
        ),
        "action": "Add 2 weeks buffer to lead times during Ramadan period.",
    },
    "monsoon_season": {
        "timing": "June to September",
        "duration_weeks": 16,
        "affected_countries": ["india", "bangladesh"],
        "impact": (
            "Flooding disrupts transportation and port operations. "
            "Inland factory access can be cut off for days."
        ),
        "action": "Avoid scheduling critical shipments during peak monsoon (July-August).",
    },
    "us_peak_season": {
        "timing": "September to November",
        "duration_weeks": 12,
        "affected_countries": ["all"],
        "impact": (
            "Shipping rates increase 2-5x. Container availability drops. "
            "Everyone is ordering for Q4 holiday season simultaneously."
        ),
        "action": "Book shipping containers by July for Q4 inventory. Expect premium rates.",
    },
}

# Supplier red flags — warning signs to watch for
SUPPLIER_RED_FLAGS = [
    "Supplier pushes for 100% payment upfront — legitimate factories accept deposits",
    "Factory address doesn't match business registration — potential trading company",
    "No third-party audit history or certifications available on request",
    "Quoted lead time is significantly shorter than industry norm — overpromising",
    "Supplier refuses pre-shipment inspection — hiding quality problems",
    "Communication quality drops after first order — attention shifts to new prospects",
    "MOQ suddenly increases after dependency is established — leverage play",
    "Supplier handles too many product categories — likely a trading company, not a factory",
]


def get_supplier_risk_insights(
    supplier_count: int, country: str
) -> dict[str, Any]:
    """Get contextual insights based on supplier setup.

    Args:
        supplier_count: Number of active suppliers
        country: Primary supplier country

    Returns:
        Relevant insights for the supplier configuration.
    """
    insights = []

    if supplier_count <= 1:
        insights.append(
            "Single supplier setup is your biggest operational risk. "
            "Every day without a backup is a gamble."
        )
    elif supplier_count == 2:
        insights.append(
            "Two suppliers is the minimum acceptable. Ensure the backup "
            "has been tested with at least one real production order."
        )
    else:
        insights.append(
            "Good diversification. Focus on maintaining relationships "
            "and keeping all suppliers warm with regular orders."
        )

    # Country-specific insight
    country_lower = country.lower()
    if country_lower == "china":
        insights.append(
            "China is the world's factory but comes with trade risk and CNY disruptions. "
            "Consider a Vietnam or Mexico backup."
        )
    elif country_lower == "india":
        insights.append(
            "India suppliers need closer quality management. "
            "Always use third-party inspection before shipping."
        )
    elif country_lower in ("vietnam", "thailand"):
        insights.append(
            f"{country} is a strong alternative to China with lower trade risk. "
            "Manufacturing capability is improving rapidly."
        )

    # Seasonal warning
    relevant_disruptions = [
        name for name, info in SEASONAL_DISRUPTIONS.items()
        if country_lower in info["affected_countries"] or "all" in info["affected_countries"]
    ]

    return {
        "insights": insights,
        "relevant_seasonal_disruptions": relevant_disruptions,
        "red_flags_to_watch": SUPPLIER_RED_FLAGS[:5],
    }


def get_heuristics() -> list[str]:
    """Get all supplier risk heuristics."""
    return HEURISTICS


def get_seasonal_disruptions(country: str | None = None) -> dict[str, Any]:
    """Get seasonal disruption calendar, optionally filtered by country."""
    if country is None:
        return SEASONAL_DISRUPTIONS

    country_lower = country.lower()
    return {
        name: info
        for name, info in SEASONAL_DISRUPTIONS.items()
        if country_lower in info["affected_countries"] or "all" in info["affected_countries"]
    }
