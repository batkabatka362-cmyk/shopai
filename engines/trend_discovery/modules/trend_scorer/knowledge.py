"""Trend scorer domain knowledge — expert heuristics for multi-signal trend evaluation.

What experienced trend analysts know:
  - "Search + marketplace agreement = strongest signal (demand + purchase)"
  - "Social only = weakest (interest does not equal purchase)"
  - "3+ signals agreeing = 70%+ confidence in trend"
  - Portfolio theory applies: diversify trend bets across categories
  - Size your bets according to confidence level
"""
from __future__ import annotations

from typing import Any


SCORING_HEURISTICS: list[str] = [
    "Search + marketplace agreement = strongest signal combo (people search AND buy)",
    "Social-only trends are the weakest signal — viral interest rarely converts to sustained purchases",
    "3+ signals agreeing on a trend = 70%+ confidence that the trend is real",
    "4/4 signals agreeing is rare but when it happens, move fast — these are 90%+ confidence",
    "When search is rising but marketplace is flat, demand exists but products are missing — opportunity",
    "When marketplace is rising but search is flat, sellers are succeeding without mass awareness — niche gold",
    "Social + emerging without search/marketplace = too early — monitor but do not invest heavily",
    "A trend scoring 60+ with 3 signals beats one scoring 80+ with 1 signal — breadth over depth",
    "Declining search + rising social = the trend peaked and is now just social media noise",
    "Signal conflicts (high search, low marketplace) mean there is a gap — could be opportunity or warning",
]

PORTFOLIO_STRATEGY: dict[str, Any] = {
    "core_principle": "Never bet everything on one trend — diversify across 2-3 trends at different stages",
    "bet_sizing": {
        "high_confidence": {
            "allocation": "40-60% of trend budget",
            "min_score": 70,
            "min_signals": 3,
            "description": "Strong multi-signal confirmation — deserves largest allocation",
            "example": "Search rising 40%, marketplace BSR improving, social mentions up — go big",
        },
        "medium_confidence": {
            "allocation": "20-35% of trend budget",
            "min_score": 45,
            "min_signals": 2,
            "description": "Promising but not fully confirmed — moderate investment",
            "example": "Search rising + early marketplace signals — launch 1-2 test products",
        },
        "low_confidence": {
            "allocation": "10-20% of trend budget",
            "min_score": 25,
            "min_signals": 1,
            "description": "Early signal or single source — small exploratory bet",
            "example": "Emerging niche signal only — create one minimal product to test",
        },
    },
    "rebalancing": [
        "Review portfolio weekly — trends move fast",
        "If a trend's composite score drops 20+ points, reduce allocation",
        "If a low-confidence bet gains new signal sources, promote it",
        "Never hold a declining trend for more than 60 days hoping for recovery",
        "When a new high-confidence trend appears, drop your weakest bet to make room",
    ],
    "diversification_rules": [
        "Spread bets across at least 2 different product categories",
        "Mix lifecycle stages: 1 proven trend + 1 emerging trend is ideal",
        "Avoid doubling down on the same audience segment",
        "If two trends serve the same customer, pick the stronger one",
    ],
}

SIGNAL_INTERPRETATION: dict[str, str] = {
    "all_high": "All signals strong — rare and extremely high confidence. Act immediately with full resources.",
    "search_marketplace_high": "Demand confirmed by purchases — the most reliable combo. Launch products.",
    "social_high_others_low": "Viral buzz without purchase behavior — likely a fad. Monitor, do not invest.",
    "emerging_high_others_low": "Very early signal — could be big in 3-6 months. Small exploratory bet.",
    "search_high_marketplace_low": "People searching but not finding/buying — supply gap. Create the product.",
    "marketplace_high_search_low": "Products selling without mass search — niche market. Optimize listings.",
    "conflicting_signals": "Signals disagree — investigate why. Often means the trend is in transition.",
    "all_low": "No strong signals anywhere — not a real trend yet. Ignore and move on.",
}


def get_scoring_heuristics() -> list[str]:
    """Return expert heuristics for trend scoring."""
    return SCORING_HEURISTICS


def get_portfolio_strategy() -> dict[str, Any]:
    """Return portfolio strategy guidance for trend betting."""
    return PORTFOLIO_STRATEGY


def interpret_signals(signal_pattern: str) -> str:
    """Return expert interpretation for a given signal pattern."""
    return SIGNAL_INTERPRETATION.get(signal_pattern, "Unknown pattern — use manual judgment.")
