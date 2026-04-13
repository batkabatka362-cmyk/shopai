"""Comparison domain knowledge — trade-off wisdom from experienced operators.

Every product choice involves trade-offs. These insights help decision-makers
understand that there is no perfect product — only products whose weaknesses
you can live with.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Core comparison truths
# --------------------------------------------------------------------------- #
COMPARISON_KNOWLEDGE: list[dict[str, str]] = [
    {
        "insight": (
            "The perfect product does not exist — every choice has trade-offs. "
            "The question is which trade-offs you can manage, not which "
            "product has no downsides."
        ),
        "context": "general",
        "severity": "critical",
    },
    {
        "insight": (
            "Choose the product with fewest CRITICAL weaknesses, not the one "
            "with the most strengths. A fatal flaw in one dimension kills "
            "the product regardless of how well it scores elsewhere."
        ),
        "context": "selection_strategy",
        "severity": "critical",
    },
    {
        "insight": (
            "High margin + low demand is usually worse than moderate margin + "
            "high demand. Volume makes businesses. You cannot optimize a "
            "product nobody wants."
        ),
        "context": "margin_vs_demand",
        "severity": "important",
    },
    {
        "insight": (
            "A product winning 3 out of 5 dimensions is not automatically the "
            "best choice. If it loses on profitability and risk, those two "
            "losses can outweigh three wins."
        ),
        "context": "dimension_counting",
        "severity": "important",
    },
    {
        "insight": (
            "When two products are within 5% of each other, pick the one "
            "you understand better. Execution advantage beats algorithmic "
            "edge every time."
        ),
        "context": "close_race",
        "severity": "moderate",
    },
    {
        "insight": (
            "Trend momentum matters more than current demand score. "
            "A product with rising demand at 60 will outperform a product "
            "with falling demand at 75 within 3 months."
        ),
        "context": "trend_factor",
        "severity": "important",
    },
    {
        "insight": (
            "Competition scores are backward-looking. By the time data shows "
            "low competition, early movers are already established. "
            "Weight trend over competition when they conflict."
        ),
        "context": "competition_lag",
        "severity": "moderate",
    },
    {
        "insight": (
            "Risk asymmetry: the downside of a risky product is losing your "
            "investment. The downside of a safe product is slow growth. "
            "Know which failure mode you prefer."
        ),
        "context": "risk_framing",
        "severity": "important",
    },
]

# --------------------------------------------------------------------------- #
#  Trade-off resolution heuristics
# --------------------------------------------------------------------------- #
TRADEOFF_HEURISTICS: dict[str, str] = {
    "margin_vs_volume": (
        "Calculate total monthly profit for both scenarios. "
        "The answer is almost always: volume wins unless margins are extreme."
    ),
    "safe_vs_risky": (
        "If you can afford to lose the investment, take the risk. "
        "If losing the investment would hurt your business, play safe."
    ),
    "trend_vs_proven": (
        "Trends are powerful but unpredictable. Allocate 70% to proven, "
        "30% to trending. Never go 100% on a trend."
    ),
    "niche_vs_mainstream": (
        "Niche products have higher margins but lower ceilings. "
        "Mainstream products have lower margins but scale better. "
        "Your goal determines the right choice."
    ),
}


def get_comparison_insight(context: str | None = None) -> list[dict[str, str]]:
    """Return comparison insights, optionally filtered by context.

    Args:
        context: Optional filter — 'general', 'selection_strategy',
                 'margin_vs_demand', 'close_race', 'trend_factor', etc.

    Returns:
        List of matching insight dicts.
    """
    if context is None:
        return list(COMPARISON_KNOWLEDGE)

    key = context.lower().replace(" ", "_").replace("-", "_")
    return [
        entry for entry in COMPARISON_KNOWLEDGE
        if entry["context"] == key
    ]


def get_tradeoff_heuristic(tradeoff_type: str) -> str:
    """Return a resolution heuristic for a specific trade-off type."""
    key = tradeoff_type.lower().replace(" ", "_").replace("-", "_")
    return TRADEOFF_HEURISTICS.get(
        key,
        "No specific heuristic available. Evaluate based on your business goals.",
    )
