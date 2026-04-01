"""Seasonality domain knowledge — expert timing intelligence.

What 10-year e-commerce veterans know about seasonal selling:
  - "Start Black Friday prep in September, not November"
  - "January fitness products: order in October, list in December"
  - "Summer products: Source in winter when factories are slow (better prices)"
  - "Never run clearance within 8 weeks of your peak"
  - "Cash reserves: save 3 months of expenses for your trough season"
"""
from __future__ import annotations

from typing import Any


# Expert timing rules
TIMING_RULES = {
    "inventory_lead_times": {
        "rule": "Order peak-season inventory at LEAST 8-12 weeks early",
        "reason": "Suppliers are busiest before peaks. Late orders = delays, higher costs, stockouts.",
        "tiers": {
            "domestic_supplier": {"lead_weeks": 4, "safety_weeks": 2},
            "international_air": {"lead_weeks": 6, "safety_weeks": 3},
            "international_sea": {"lead_weeks": 12, "safety_weeks": 4},
        },
    },
    "marketing_ramp": {
        "rule": "Start marketing campaigns 4-6 weeks before peak",
        "reason": "Algorithms need 2+ weeks to optimize. Start early for best CPAs.",
        "phases": [
            {"weeks_before": 6, "action": "Launch awareness campaigns", "budget_pct": 20},
            {"weeks_before": 4, "action": "Start retargeting, email teasers", "budget_pct": 30},
            {"weeks_before": 2, "action": "Full campaign launch, daily optimization", "budget_pct": 40},
            {"weeks_before": 0, "action": "Peak week: max budget, flash deals", "budget_pct": 100},
        ],
    },
    "pricing_strategy": {
        "rule": "Never discount during rising demand; save discounts for declining periods",
        "phases": {
            "pre_peak": "Build anticipation. No discounts. Tease upcoming deals.",
            "peak": "Strategic discounts on loss leaders. Maintain price on bestsellers.",
            "post_peak": "Gradual markdown: 20% week 1, 30% week 2, 50% week 3.",
            "trough": "Bundle deals to maintain AOV. Free shipping offers.",
        },
    },
    "content_calendar": {
        "rule": "Create seasonal content 8 weeks ahead, publish 4 weeks ahead",
        "reason": "SEO content takes 4-8 weeks to rank. Social content needs planning.",
        "approach": "Batch-create content during slow season for busy season.",
    },
}

# Category-specific expert knowledge
CATEGORY_TIMING_KNOWLEDGE = {
    "fitness": {
        "golden_window": "December 15 - January 31",
        "strategy": "Launch New Year campaigns Dec 26. People buy equipment before Jan 1 resolution.",
        "pitfall": "Don't invest heavily in fitness marketing after February — interest drops 50%.",
        "inventory_tip": "Order in October. By November, fitness suppliers are swamped.",
    },
    "swimwear": {
        "golden_window": "March - May",
        "strategy": "Launch spring break campaigns in February. Summer body marketing in March.",
        "pitfall": "Inventory left after July is dead stock. Start clearance Aug 1.",
        "inventory_tip": "Source in November-December when factories are idle (30% cost savings).",
    },
    "toys_games": {
        "golden_window": "October - December",
        "strategy": "Gift guides in October. Black Friday doorbusters. Christmas countdown in December.",
        "pitfall": "95% of toy sales happen in Q4. Don't overstock for Q1-Q3.",
        "inventory_tip": "Order August latest. Toy factories are 100% booked by September.",
    },
    "jewelry": {
        "golden_window": "January 20 - February 14 AND November 15 - December 25",
        "strategy": "Valentine's: 'perfect gift' messaging. Christmas: luxury gift guides.",
        "pitfall": "March-April is dead zone for jewelry. Don't spend on ads.",
        "inventory_tip": "Personalized jewelry needs extra lead time (3-4 weeks for engraving).",
    },
    "home_garden": {
        "golden_window": "March - May",
        "strategy": "Spring cleaning + gardening season. Pinterest marketing works well here.",
        "pitfall": "Heavy items (furniture) have high shipping costs year-round.",
        "inventory_tip": "Source patio/garden items in winter for spring launch.",
    },
    "electronics": {
        "golden_window": "November - December",
        "strategy": "Black Friday/Cyber Monday is EVERYTHING. Price-match guarantee important.",
        "pitfall": "Electronics depreciate fast. Don't sit on inventory past January.",
        "inventory_tip": "New models launch in September — buy last-gen for clearance margins.",
    },
}

# Cash flow management by seasonality type
CASH_FLOW_GUIDANCE = {
    "highly_seasonal": {
        "reserve_months": 4,
        "guidance": "Save 4 months of operating expenses during peak. "
                    "Trough months will have 40-60% less revenue.",
        "strategy": "During peak: maximize revenue, don't spend all profit. "
                    "During trough: minimize expenses, focus on content/SEO (free traffic).",
    },
    "moderately_seasonal": {
        "reserve_months": 2,
        "guidance": "Save 2 months of expenses. Revenue swings 20-40%.",
        "strategy": "Spread marketing budget unevenly — more in peaks, less in troughs.",
    },
    "slightly_seasonal": {
        "reserve_months": 1,
        "guidance": "Minimal seasonal impact. 1 month reserve is sufficient.",
        "strategy": "Steady operations. Small adjustments to inventory and marketing.",
    },
    "non_seasonal": {
        "reserve_months": 1,
        "guidance": "No significant seasonal impact. Standard cash management.",
        "strategy": "Focus on growth metrics rather than seasonal planning.",
    },
}


def get_timing_rules() -> dict[str, Any]:
    """Get expert timing rules for seasonal operations."""
    return TIMING_RULES


def get_category_timing(category: str) -> dict[str, Any]:
    """Get category-specific timing knowledge."""
    cat = category.lower().replace(" ", "_").replace("-", "_")
    if cat in CATEGORY_TIMING_KNOWLEDGE:
        return CATEGORY_TIMING_KNOWLEDGE[cat]
    for key in CATEGORY_TIMING_KNOWLEDGE:
        if cat in key or key in cat:
            return CATEGORY_TIMING_KNOWLEDGE[key]
    return {
        "golden_window": "Category-specific timing not available",
        "strategy": "Follow general e-commerce seasonal patterns (Q4 peak)",
        "pitfall": "Don't assume your category follows the general pattern",
        "inventory_tip": "Track your own sales data for 12 months to build custom profile",
    }


def get_cash_flow_guidance(classification: str) -> dict[str, Any]:
    """Get cash flow management guidance based on seasonality classification."""
    return CASH_FLOW_GUIDANCE.get(classification, CASH_FLOW_GUIDANCE["moderately_seasonal"])


def get_prep_checklist(weeks_to_peak: int) -> list[dict[str, Any]]:
    """Get a preparation checklist based on weeks until peak season."""
    checklist = []

    if weeks_to_peak >= 12:
        checklist.append({"priority": "low", "action": "Start sourcing/ordering inventory from international suppliers"})
        checklist.append({"priority": "low", "action": "Plan seasonal content calendar"})

    if weeks_to_peak >= 8:
        checklist.append({"priority": "medium", "action": "Order inventory from domestic suppliers"})
        checklist.append({"priority": "medium", "action": "Create seasonal product photography"})
        checklist.append({"priority": "medium", "action": "Plan email marketing sequences"})

    if weeks_to_peak >= 6:
        checklist.append({"priority": "medium", "action": "Launch awareness ad campaigns"})
        checklist.append({"priority": "medium", "action": "Update product descriptions with seasonal keywords"})
        checklist.append({"priority": "medium", "action": "Test website load capacity"})

    if weeks_to_peak >= 4:
        checklist.append({"priority": "high", "action": "Start retargeting campaigns"})
        checklist.append({"priority": "high", "action": "Send email teasers to subscriber list"})
        checklist.append({"priority": "high", "action": "Set up cart recovery automation"})

    if weeks_to_peak >= 2:
        checklist.append({"priority": "critical", "action": "Full campaign launch"})
        checklist.append({"priority": "critical", "action": "Verify all inventory has arrived"})
        checklist.append({"priority": "critical", "action": "Prepare customer support for volume increase"})

    if weeks_to_peak >= 0:
        checklist.append({"priority": "critical", "action": "Daily performance monitoring"})
        checklist.append({"priority": "critical", "action": "Restock fast movers immediately"})
        checklist.append({"priority": "critical", "action": "Optimize ads based on real-time data"})

    return checklist
