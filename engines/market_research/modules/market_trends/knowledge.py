"""Market trends domain knowledge — what experienced operators know about trends.

Expert-level pattern recognition:
  - How to distinguish real trends from fads
  - When to enter and when to wait
  - Historical pattern matching
  - Category lifecycle understanding
"""
from __future__ import annotations

from typing import Any


# Trend lifecycle pattern (typical duration in months)
TREND_LIFECYCLE = {
    "emergence": {
        "duration_months": "3-6",
        "characteristics": [
            "Social media early adopters posting",
            "Search volume just starting to rise",
            "Very few competitors",
            "No established brands in the niche",
        ],
        "opportunity": "First-mover advantage, but risky",
        "examples": ["Fidget spinners (2016)", "CBD products (2018)", "AI accessories (2024)"],
    },
    "growth": {
        "duration_months": "6-24",
        "characteristics": [
            "Search volume growing 30-100% YoY",
            "Mainstream media coverage",
            "Multiple competitors entering",
            "Review volume increasing",
        ],
        "opportunity": "Best time to enter — trend confirmed but not saturated",
        "examples": ["Athleisure (2017-2019)", "Home office (2020-2021)", "Pet wellness (2022-2024)"],
    },
    "peak": {
        "duration_months": "6-12",
        "characteristics": [
            "Search volume plateauing",
            "Market flooded with competitors",
            "Price competition intensifying",
            "News articles about 'the trend'",
        ],
        "opportunity": "Only for differentiated players — commodity risk high",
        "examples": ["Dropshipping (2019)", "NFT merch (2022)", "Fast fashion (2020)"],
    },
    "decline": {
        "duration_months": "12-36",
        "characteristics": [
            "Search volume declining",
            "Competitors exiting",
            "Price drops as remaining players liquidate",
            "Consumer fatigue",
        ],
        "opportunity": "Avoid — invest resources elsewhere",
        "examples": ["Fidget spinners (2018)", "COVID masks (2022)", "Printed leggings (2023)"],
    },
}

# Fad vs trend distinguishing patterns
FAD_VS_TREND_PATTERNS = {
    "likely_fad": [
        "Single platform virality (only TikTok, no search/review growth)",
        "Growth rate > 300% in < 3 months",
        "No repeat purchase behavior (one-time novelty)",
        "Product has no functional improvement over alternatives",
        "Celebrity-driven without underlying need",
    ],
    "likely_trend": [
        "Multiple platforms showing growth simultaneously",
        "Gradual growth over 6+ months",
        "Repeat purchase rates increasing",
        "Addresses real consumer need or shift in values",
        "Supported by demographic or cultural changes",
    ],
    "permanent_shift": [
        "Enabled by technology change (mobile, AI, etc.)",
        "Driven by generational values (sustainability, wellness)",
        "Regulatory or environmental forcing function",
        "Infrastructure being built around it",
    ],
}

# Category timing intelligence
TIMING_INTELLIGENCE = {
    "seasonal_entries": {
        "rule": "Enter seasonal markets 3-4 months BEFORE peak",
        "examples": {
            "swimwear": "Start marketing in February, not June",
            "christmas_gifts": "Launch in September, not November",
            "fitness": "January ads start December preparation",
            "outdoor": "Spring products need winter prep",
        },
    },
    "trend_entries": {
        "rule": "Enter growing trends when search growth is 30-80% — not before, not after",
        "too_early": "< 30% search growth means unproven demand",
        "sweet_spot": "30-80% search growth with multiple signal confirmation",
        "too_late": "> 100% with many competitors means you missed the window",
    },
    "counter_seasonal": {
        "rule": "Source and prepare during off-peak when suppliers have capacity",
        "benefit": "Better prices, faster production, less competition for supplier attention",
    },
}


def get_trend_lifecycle() -> dict[str, Any]:
    """Get the full trend lifecycle model."""
    return TREND_LIFECYCLE


def get_fad_patterns() -> dict[str, Any]:
    """Get fad vs trend distinction patterns."""
    return FAD_VS_TREND_PATTERNS


def get_timing_intelligence() -> dict[str, Any]:
    """Get expert timing guidance."""
    return TIMING_INTELLIGENCE


def classify_trend_stage(
    growth_rate: float,
    competitor_count: int,
    months_since_emergence: int,
) -> dict[str, Any]:
    """Classify which lifecycle stage a trend is in.

    Args:
        growth_rate: YoY search growth %
        competitor_count: Number of active competitors
        months_since_emergence: How long the trend has been visible
    """
    if months_since_emergence < 6 and growth_rate > 50 and competitor_count < 10:
        stage = "emergence"
    elif growth_rate > 20 and competitor_count < 100:
        stage = "growth"
    elif growth_rate > -10 and competitor_count >= 50:
        stage = "peak"
    else:
        stage = "decline"

    lifecycle = TREND_LIFECYCLE[stage]

    return {
        "stage": stage,
        "duration": lifecycle["duration_months"],
        "characteristics": lifecycle["characteristics"],
        "opportunity": lifecycle["opportunity"],
        "recommendation": _stage_recommendation(stage, growth_rate, competitor_count),
    }


def _stage_recommendation(stage: str, growth: float, competitors: int) -> str:
    """Generate specific recommendation based on stage."""
    if stage == "emergence":
        if growth > 100:
            return "High-risk, high-reward. Test with small inventory first."
        return "Too early. Monitor search trends weekly. Enter when growth > 30% for 3+ months."

    if stage == "growth":
        if competitors < 20:
            return "IDEAL entry point. Low competition, confirmed demand. Act now."
        if competitors < 50:
            return "Good entry point. Need differentiation. Focus on brand and content."
        return "Late growth phase. Strong differentiation required. Consider sub-niche."

    if stage == "peak":
        return f"Market saturated ({competitors} competitors). Only enter with unique product or strong brand."

    return "Market declining. Avoid unless you can acquire competitors cheaply."
