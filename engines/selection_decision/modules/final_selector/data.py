"""Final selector data — thresholds, action templates, outcome benchmarks.

Reference data for making and validating the final product selection.
These thresholds are calibrated against real Shopify store launches.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Selection thresholds
# --------------------------------------------------------------------------- #
SELECTION_THRESHOLDS: dict[str, Any] = {
    "min_confidence": 40.0,
    "min_unified_score": 30.0,
    "max_risk_level": "high",
    "min_profitability_score": 20.0,
    "risk_level_order": ["low", "moderate", "medium", "high", "critical"],
    "auto_select_confidence": 70.0,
    "backup_min_score_ratio": 0.60,
}

# --------------------------------------------------------------------------- #
#  Action plan templates by confidence level
# --------------------------------------------------------------------------- #
ACTION_PLAN_TEMPLATES: dict[str, dict[str, Any]] = {
    "high_confidence": {
        "label": "Full Launch",
        "steps": [
            "Source initial inventory (100-200 units based on demand projection)",
            "Set up product listing with optimized copy and images",
            "Launch ads at $20-50/day to validate demand",
            "Monitor first 7 days: target 2% conversion rate",
            "Scale ad spend if ROAS > 2.5x after week 1",
            "Reorder at 60% inventory depletion",
        ],
        "timeline": "2-4 weeks to first reorder decision",
        "budget_allocation": {"inventory": 0.50, "ads": 0.30, "operations": 0.20},
    },
    "medium_confidence": {
        "label": "Test Launch",
        "steps": [
            "Source small test batch (25-50 units)",
            "Create minimal product listing",
            "Run targeted ads at $10-20/day for 2 weeks",
            "Set hard stop-loss: pause if ROAS < 1.5x after 10 days",
            "Evaluate: proceed to full launch or pivot to backup product",
            "Schedule 2-week review checkpoint",
        ],
        "timeline": "2-3 weeks to go/no-go decision",
        "budget_allocation": {"inventory": 0.35, "ads": 0.40, "operations": 0.25},
    },
    "low_confidence": {
        "label": "Validation Only",
        "steps": [
            "Do NOT order inventory yet",
            "Create a landing page with email capture",
            "Run $5-10/day ads to test demand signal",
            "Survey potential customers on willingness to buy",
            "Gather 3 competing supplier quotes",
            "Re-evaluate with more data in 1-2 weeks",
        ],
        "timeline": "1-2 weeks to gather validation data",
        "budget_allocation": {"validation": 0.60, "ads": 0.30, "research": 0.10},
    },
}

# --------------------------------------------------------------------------- #
#  Expected outcome benchmarks by score tier
# --------------------------------------------------------------------------- #
EXPECTED_OUTCOME_BENCHMARKS: list[dict[str, Any]] = [
    {
        "score_range": (80, 100),
        "tier": "excellent",
        "expected_success_rate": 0.75,
        "typical_monthly_revenue": (5000, 25000),
        "typical_roas": (3.0, 6.0),
        "typical_margin": (25, 45),
        "time_to_profitability": "1-3 weeks",
    },
    {
        "score_range": (60, 80),
        "tier": "good",
        "expected_success_rate": 0.58,
        "typical_monthly_revenue": (2000, 10000),
        "typical_roas": (2.0, 4.0),
        "typical_margin": (20, 35),
        "time_to_profitability": "2-6 weeks",
    },
    {
        "score_range": (40, 60),
        "tier": "moderate",
        "expected_success_rate": 0.38,
        "typical_monthly_revenue": (500, 5000),
        "typical_roas": (1.5, 2.5),
        "typical_margin": (15, 28),
        "time_to_profitability": "4-10 weeks",
    },
    {
        "score_range": (20, 40),
        "tier": "weak",
        "expected_success_rate": 0.18,
        "typical_monthly_revenue": (100, 2000),
        "typical_roas": (0.8, 1.5),
        "typical_margin": (8, 20),
        "time_to_profitability": "8+ weeks (if at all)",
    },
    {
        "score_range": (0, 20),
        "tier": "poor",
        "expected_success_rate": 0.05,
        "typical_monthly_revenue": (0, 500),
        "typical_roas": (0.0, 0.8),
        "typical_margin": (0, 10),
        "time_to_profitability": "Unlikely to reach profitability",
    },
]


def get_action_plan(confidence_level: str) -> dict[str, Any]:
    """Return the action plan template for a confidence level."""
    key = confidence_level.lower().strip()
    mapping = {"high": "high_confidence", "medium": "medium_confidence", "low": "low_confidence"}
    template_key = mapping.get(key, "low_confidence")
    return ACTION_PLAN_TEMPLATES[template_key]


def get_outcome_benchmark(unified_score: float) -> dict[str, Any]:
    """Return expected outcome benchmarks for a given unified score."""
    for bench in EXPECTED_OUTCOME_BENCHMARKS:
        lo, hi = bench["score_range"]
        if lo <= unified_score < hi:
            return bench
    return EXPECTED_OUTCOME_BENCHMARKS[-1]
