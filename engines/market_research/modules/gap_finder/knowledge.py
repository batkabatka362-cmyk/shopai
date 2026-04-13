"""Gap finder domain knowledge — expert-level gap exploitation strategies.

What veterans know about finding and exploiting market gaps:
  - "The best products solve a specific complaint, not a general need"
  - "Read 1-star reviews of top sellers — that's your product roadmap"
  - "Price gaps are least reliable — there might be a reason nobody sells there"
  - "Demand-supply gaps close fast — you have 3-6 months before competitors follow"
  - "The gap that nobody sees is the gap between perceived and actual value"
"""
from __future__ import annotations

from typing import Any


# Expert strategies per gap type
GAP_EXPLOITATION_STRATEGIES = {
    "demand_supply_gap": {
        "strategy": "Speed to market",
        "playbook": [
            "Find the product that matches the high-demand keyword",
            "Source fastest option (even if not cheapest) — speed = advantage",
            "Create listing optimized for the exact search terms",
            "Launch ads targeting the keyword immediately",
            "Expect 3-6 months before competitors copy — maximize early profit",
        ],
        "common_mistake": "Spending too long perfecting the product. MVP that ships beats perfect that doesn't.",
        "success_metric": "Page 1 ranking for target keyword within 60 days",
    },
    "quality_gap": {
        "strategy": "Premium positioning",
        "playbook": [
            "Study ALL 1-star reviews of top 5 competitors",
            "Build product that fixes the top 3 complaints",
            "Invest in professional photography (5-10x competitor quality)",
            "Price 20-40% above competitors — premium attracts quality seekers",
            "Offer unconditional guarantee — removes purchase risk",
            "Encourage photo reviews — visual proof of quality",
        ],
        "common_mistake": "Pricing at competitor level. Premium product at commodity price devalues your brand.",
        "success_metric": "Average rating 4.5+ after 50 reviews",
    },
    "complaint_gap": {
        "strategy": "Direct response to pain",
        "playbook": [
            "Identify the EXACT complaint (not vague 'quality' — specific like 'handle breaks after 2 months')",
            "Engineer product to specifically address it",
            "In title/bullets: explicitly state you fixed the problem",
            "Example: 'Reinforced handle — designed to last 5+ years'",
            "Collect reviews that mention the fix",
            "Run comparison content: 'Other products break → ours doesn't'",
        ],
        "common_mistake": "Fixing too many things. Fix ONE thing better than anyone. That's your hook.",
        "success_metric": "Zero complaints about the specific issue in first 100 reviews",
    },
    "price_gap": {
        "strategy": "Tier filling",
        "playbook": [
            "Verify the gap is real — maybe the tier doesn't sell (test first)",
            "Source product at cost that supports the target price point",
            "Position clearly: 'Premium quality at mid-range price' or 'Affordable version of luxury'",
            "Small initial order — validate demand before scaling",
        ],
        "common_mistake": "Assuming empty tier = opportunity. Sometimes there's no product because there's no demand at that price.",
        "success_metric": "Sustainable sales velocity within 30 days of launch",
    },
    "competitor_weakness": {
        "strategy": "Better execution",
        "playbook": [
            "Don't reinvent — replicate the product, improve the experience",
            "Better photos: lifestyle images, not just white background",
            "Better descriptions: benefit-focused, not feature-focused",
            "Faster shipping: 2-day if possible",
            "Better customer service: respond to every question within 4 hours",
            "Better reviews: follow-up email sequence to collect reviews",
        ],
        "common_mistake": "Trying to compete on price. Compete on EXPERIENCE.",
        "success_metric": "Higher rating than top competitor within 90 days",
    },
    "new_market_gap": {
        "strategy": "Controlled exploration",
        "playbook": [
            "SMALL bet — minimum viable inventory (50-100 units max)",
            "Test with ads: if CPA > AOV × 0.3, market isn't ready",
            "Monitor search trends weekly — is demand growing?",
            "If 30-day test profitable → double down. If not → cut losses.",
            "Be ready to be wrong — most new markets fail",
        ],
        "common_mistake": "Going all-in on unproven market. Always test small first.",
        "success_metric": "Profitable unit economics within 30-day test",
    },
}

# Review mining intelligence
REVIEW_MINING_GUIDE = {
    "where_to_look": [
        "Amazon 1-2 star reviews of top 10 sellers in category",
        "Reddit threads about the product type",
        "Facebook groups where customers discuss the category",
        "YouTube review comments (negative ones)",
        "Trust Pilot and Google Reviews for competitor stores",
    ],
    "what_to_extract": [
        "Specific product failures (not vague complaints)",
        "Feature requests (what people wish the product had)",
        "Price sensitivity signals (too expensive / would pay more for X)",
        "Use case mismatches (bought for X, doesn't work for X)",
        "Comparison mentions (wish it was like [other product])",
    ],
    "how_to_quantify": {
        "method": "Count mentions of each complaint across 100+ reviews",
        "threshold": "If >10% mention same issue → validated gap",
        "priority": "Most-mentioned complaint = highest-priority gap",
    },
}

# Gap validation framework
VALIDATION_FRAMEWORK = {
    "level_1_hypothesis": {
        "effort": "1 hour",
        "actions": ["Check search volume", "Count competitors", "Read 20 reviews"],
        "pass_criteria": "Search volume > 1000 AND <50 competitors AND negative review pattern found",
    },
    "level_2_research": {
        "effort": "1 day",
        "actions": ["Deep review mining (100+ reviews)", "Price analysis", "Supplier search"],
        "pass_criteria": "Clear product spec AND viable margin AND available supplier",
    },
    "level_3_test": {
        "effort": "2-4 weeks",
        "actions": ["Order sample", "Create listing", "Run $200 ad test"],
        "pass_criteria": "CPA < AOV × 0.3 AND conversion rate > 1.5%",
    },
    "level_4_launch": {
        "effort": "4-8 weeks",
        "actions": ["Order 100-500 units", "Full listing optimization", "Launch marketing"],
        "pass_criteria": "Profitable in 60 days with growing velocity",
    },
}


def get_exploitation_strategy(gap_type: str) -> dict[str, Any]:
    """Get expert strategy for exploiting a specific gap type."""
    return GAP_EXPLOITATION_STRATEGIES.get(gap_type, {
        "strategy": "Research first",
        "playbook": ["Investigate the gap further before committing resources"],
        "common_mistake": "Acting without sufficient data",
        "success_metric": "Define clear success criteria before starting",
    })


def get_review_mining_guide() -> dict[str, Any]:
    """Get guide for mining competitor reviews for gaps."""
    return REVIEW_MINING_GUIDE


def get_validation_framework() -> dict[str, Any]:
    """Get staged validation framework for testing gaps."""
    return VALIDATION_FRAMEWORK
