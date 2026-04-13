"""Demand trend domain knowledge — expert heuristics and market stage wisdom.

What a 10-year e-commerce veteran knows about demand trends:
  - "Growing demand forgives mistakes — you grow WITH the market"
  - "Declining demand = stealing market share (much harder)"
  - "Flat demand = mature market, need differentiation to win"
  - "Don't confuse seasonal spikes with real growth"
"""
from __future__ import annotations

from typing import Any


# Core demand trend heuristics — hard-won wisdom from real e-commerce operations
HEURISTICS = [
    "Growing demand forgives mistakes — you grow WITH the market.",
    "Declining demand = stealing market share (much harder). You must out-execute.",
    "Flat demand = mature market, need differentiation to win. Price wars destroy everyone.",
    "Don't confuse seasonal spikes with real growth — always compare YoY, not MoM.",
    "A 10% YoY growth rate means the market doubles in 7 years. That's powerful compounding.",
    "Two months of data is the minimum. Three months gives real signal. Six months = reliable.",
    "If search volume is growing but sales are flat, there's a conversion problem, not a demand problem.",
    "Trends that spike >100% in a month are usually fads. Sustainable growth is 5-15%/month.",
    "Category growth matters more than product growth in year 1. Ride the wave, don't fight it.",
    "The best time to enter a market is during early growth. Mature markets require 10x more effort.",
]

# Market stage advice — what to do at each stage of market lifecycle
MARKET_STAGE_ADVICE = {
    "early_growth": {
        "stage": "Early Growth",
        "description": "Market is expanding rapidly. New customers entering daily. "
                       "Competition is still low. First-mover advantage matters.",
        "strategy": "Move fast, capture customers, build brand recognition. "
                    "Margins are less important than market share right now.",
        "risk_level": "medium",
        "opportunity_level": "very_high",
        "time_sensitivity": "High — window closes as competitors enter",
        "key_metrics": ["customer acquisition rate", "market share", "brand awareness"],
    },
    "growth": {
        "stage": "Growth",
        "description": "Market is growing steadily. Competitors are entering. "
                       "Customers have choices but demand exceeds supply.",
        "strategy": "Differentiate and build loyalty. Focus on product quality, "
                    "reviews, and customer experience. Lock in repeat customers.",
        "risk_level": "low",
        "opportunity_level": "high",
        "time_sensitivity": "Moderate — still a good time to enter",
        "key_metrics": ["repeat purchase rate", "review quality", "organic traffic"],
    },
    "mature": {
        "stage": "Mature",
        "description": "Market growth has slowed. Established players dominate. "
                       "Customers have strong preferences and brand loyalty.",
        "strategy": "Find underserved niches within the category. Compete on "
                    "specialization, not breadth. Build a community around your brand.",
        "risk_level": "medium_high",
        "opportunity_level": "medium",
        "time_sensitivity": "Low — market will be here, but so will competitors",
        "key_metrics": ["niche market share", "customer LTV", "margin optimization"],
    },
    "declining": {
        "stage": "Declining",
        "description": "Market is shrinking. Customers are leaving for alternatives. "
                       "Competitors are exiting or consolidating.",
        "strategy": "Generally avoid. If you must enter, target the most loyal "
                    "remaining customers with premium offerings. Keep investment minimal.",
        "risk_level": "high",
        "opportunity_level": "low",
        "time_sensitivity": "N/A — timing won't help a declining market",
        "key_metrics": ["profitability", "cash flow", "exit timing"],
    },
}

# Trend-specific insights for decision-making
TREND_INSIGHTS = {
    "rapid_growth": {
        "insight": "Rapid growth (>8%/month) is exciting but dangerous. It attracts "
                   "competitors fast and can mask underlying problems. Validate that "
                   "growth is organic, not driven by a single viral moment.",
        "action": "Enter quickly but keep first inventory order small. Scale up as "
                  "you validate the trend is sustainable.",
        "watch_for": "Sudden competitor influx, price wars, supply chain strain.",
    },
    "moderate_growth": {
        "insight": "Moderate growth (3-8%/month) is the sweet spot. It's enough to "
                   "expand the market but not so fast that it attracts everyone.",
        "action": "Enter with confidence. Invest in branding and customer acquisition. "
                  "This is where sustainable businesses are built.",
        "watch_for": "Category lifecycle stage — is this growth or recovery?",
    },
    "stable": {
        "insight": "Stable demand means the market has matured. Winners and losers are "
                   "mostly decided. Entering now requires clear differentiation.",
        "action": "Only enter if you have a unique angle (product, brand, price, niche). "
                  "Generic products will fail in a stable market.",
        "watch_for": "Margin compression, commoditization, private label competition.",
    },
    "declining": {
        "insight": "Declining demand means the market is shrinking. Every customer you "
                   "gain is one someone else lost. This is a zero-sum game.",
        "action": "Generally avoid. If entering, target a shrink-proof niche (e.g., "
                  "enthusiasts, collectors). Keep costs minimal.",
        "watch_for": "Accelerating decline, competitor exit (may create short-term opportunity).",
    },
}


def get_heuristics() -> list[str]:
    """Get core demand trend heuristics."""
    return HEURISTICS


def get_trend_insight(velocity_class: str) -> dict[str, Any]:
    """Get expert insight based on trend velocity classification.

    Args:
        velocity_class: "rapid_growth" | "moderate_growth" | "stable" | "declining"
    """
    return TREND_INSIGHTS.get(velocity_class, {
        "insight": "Trend velocity is unclear — collect more data before deciding.",
        "action": "Wait for 2-3 more months of data to establish a clear trend.",
        "watch_for": "Any sudden changes in direction or velocity.",
    })


def get_market_stage_advice(lifecycle_stage: str) -> dict[str, Any]:
    """Get strategic advice for a market lifecycle stage.

    Args:
        lifecycle_stage: "early_growth" | "growth" | "mature" | "declining"
    """
    return MARKET_STAGE_ADVICE.get(lifecycle_stage, {
        "stage": "Unknown",
        "description": "Market lifecycle stage is unclear.",
        "strategy": "Gather more data on market size trends, competitor entry/exit, "
                    "and customer behavior before making strategic decisions.",
        "risk_level": "unknown",
        "opportunity_level": "unknown",
        "time_sensitivity": "Unknown",
        "key_metrics": ["market research depth", "competitor analysis"],
    })
