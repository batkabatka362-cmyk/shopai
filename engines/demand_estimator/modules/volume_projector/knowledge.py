"""Volume projector domain knowledge — expert heuristics and guidance.

What a 10-year e-commerce veteran knows about sales volume:
  - "Month 1 sales = 40% of expected — don't panic"
  - "Order 2 months inventory + 30% buffer"
  - "If projected volume < 30/month at target price, margins won't work"
  - "Q4 volume can be 150-200% of average — plan inventory accordingly"
"""
from __future__ import annotations

from typing import Any


# Core volume heuristics — hard-won wisdom from real e-commerce operations
HEURISTICS = [
    "Month 1 sales = 40% of expected — don't panic. This is normal ramp-up.",
    "Order 2 months inventory + 30% buffer. Running out of stock kills momentum.",
    "If projected volume < 30/month at target price, margins won't work.",
    "Q4 (Oct-Dec) volume can be 150-200% of average — pre-order inventory in August.",
    "Q1 (Jan-Mar) is the slowest period — don't judge a product by January sales.",
    "Reorder at 60% depletion, not when shelves are empty. Lead time is real.",
    "First batch should be small (test batch). Second batch should be 2x if sales validate.",
    "Volume projections are wrong — they're just less wrong than guessing.",
    "3 months of data beats any projection model. Validate fast, adjust faster.",
    "Subscription products need 50% fewer new customers to maintain volume.",
]

# Ramp-up guidance — what to expect and when to worry
RAMP_GUIDANCE = {
    "month_1": {
        "expected_pct": 40,
        "guidance": "40% of steady-state volume. Focus on getting reviews and "
                    "optimizing listings, not panicking about sales numbers.",
        "action": "Collect reviews, fix listing issues, tune ad targeting.",
    },
    "month_2": {
        "expected_pct": 55,
        "guidance": "55% of steady-state. You should see improvement from month 1. "
                    "If volume is flat or declining, investigate product-market fit.",
        "action": "Analyze ad performance, check review sentiment, compare to projection.",
    },
    "month_3": {
        "expected_pct": 65,
        "guidance": "65% of steady-state. The product should be finding its audience. "
                    "This is your first real signal of long-term viability.",
        "action": "Decide whether to scale up or cut losses. 3-month data is meaningful.",
    },
    "month_6": {
        "expected_pct": 90,
        "guidance": "90% of steady-state. Product should be near full velocity. "
                    "If still below 70%, something is fundamentally wrong.",
        "action": "Scale inventory if on track. Pivot or discontinue if far below target.",
    },
    "month_9_plus": {
        "expected_pct": 100,
        "guidance": "Full steady-state velocity. Volume should be stable or growing. "
                    "Focus shifts from ramp-up to optimization and expansion.",
        "action": "Optimize margins, explore variations/bundles, scale ad spend.",
    },
}

# Volume insights by scenario
VOLUME_INSIGHTS = {
    "very_low": {
        "threshold": 15,
        "insight": "Under 15 units/month is hobby-level volume. Per-unit costs will "
                   "be high, shipping rates will be retail-level, and margins will "
                   "be razor-thin. Consider bundling or finding higher-demand products.",
        "recommendation": "Don't launch unless this is a high-ticket item (>$100).",
    },
    "low": {
        "threshold": 30,
        "insight": "15-30 units/month is borderline viable. You can make it work with "
                   "high margins (>50%) but there's very little room for error.",
        "recommendation": "Proceed only with proven demand signals and 50%+ margins.",
    },
    "viable": {
        "threshold": 100,
        "insight": "30-100 units/month is solid small-business volume. You can negotiate "
                   "decent supplier rates and shipping discounts start to apply.",
        "recommendation": "Good starting point. Focus on getting to 100+/month.",
    },
    "good": {
        "threshold": 300,
        "insight": "100-300 units/month is healthy volume. Supplier negotiations become "
                   "much easier, and you can afford to invest in marketing and branding.",
        "recommendation": "Scale marketing, consider product line extensions.",
    },
    "excellent": {
        "threshold": 1000,
        "insight": "300+ units/month is strong volume. You have leverage with suppliers, "
                   "can optimize fulfillment, and marketing costs per unit drop.",
        "recommendation": "Optimize operations, negotiate better terms, expand SKUs.",
    },
}


def get_heuristics() -> list[str]:
    """Get core volume projection heuristics."""
    return HEURISTICS


def get_volume_insight(monthly_units: float) -> dict[str, Any]:
    """Get expert insight based on projected monthly volume."""
    if monthly_units < 15:
        return VOLUME_INSIGHTS["very_low"]
    if monthly_units < 30:
        return VOLUME_INSIGHTS["low"]
    if monthly_units < 100:
        return VOLUME_INSIGHTS["viable"]
    if monthly_units < 300:
        return VOLUME_INSIGHTS["good"]
    return VOLUME_INSIGHTS["excellent"]


def get_ramp_guidance(product_age_months: int) -> dict[str, Any]:
    """Get ramp-up guidance for a product at a given age."""
    if product_age_months <= 1:
        return RAMP_GUIDANCE["month_1"]
    if product_age_months <= 2:
        return RAMP_GUIDANCE["month_2"]
    if product_age_months <= 3:
        return RAMP_GUIDANCE["month_3"]
    if product_age_months <= 6:
        return RAMP_GUIDANCE["month_6"]
    return RAMP_GUIDANCE["month_9_plus"]
