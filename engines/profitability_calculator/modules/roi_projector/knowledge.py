"""ROI projector knowledge — expert insights on ROI."""
from __future__ import annotations
from typing import Any

ROI_KNOWLEDGE = {
    "month_1_always_negative": "Month 1 is always negative — launch costs, ad learning period, no reviews yet. This is NORMAL.",
    "compounding": "ROI compounds: month 3 velocity is typically 2x month 1 due to reviews + SEO + ad optimization.",
    "opportunity_cost": "Compare to alternatives: S&P 500 returns ~10%/year. Your time has a cost too ($50-100/hour).",
    "break_even_timing": "Most successful Shopify products break even in month 2-3. If not by month 4, reassess.",
    "seasonal_impact": "Q4 (Nov-Dec) can be 2-3x normal months. Factor this into annual ROI projections.",
    "ad_optimization": "Ad ROAS improves 30-50% from month 1 to month 3 as algorithm learns. Don't judge too early.",
}

def get_roi_insight(context: str = "") -> str:
    ctx = context.lower()
    if "negative" in ctx or "loss" in ctx:
        return ROI_KNOWLEDGE["month_1_always_negative"]
    if "compound" in ctx or "grow" in ctx:
        return ROI_KNOWLEDGE["compounding"]
    if "compare" in ctx or "alternative" in ctx:
        return ROI_KNOWLEDGE["opportunity_cost"]
    return ROI_KNOWLEDGE["break_even_timing"]
