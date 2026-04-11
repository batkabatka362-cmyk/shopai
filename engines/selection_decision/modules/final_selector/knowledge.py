"""Final selector domain knowledge — wisdom for the moment of decision.

The final selection is where analysis meets action. These insights ensure
decision-makers understand that execution matters more than optimization,
and having a backup plan is not optional.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Core selection truths
# --------------------------------------------------------------------------- #
SELECTION_KNOWLEDGE: list[dict[str, str]] = [
    {
        "insight": (
            "The best product is the one you can execute on — skill matters "
            "more than score. A 65-point product you know how to sell beats "
            "an 85-point product in an unfamiliar niche."
        ),
        "context": "execution",
        "severity": "critical",
    },
    {
        "insight": (
            "Always have a backup — your #1 pick might not work out. "
            "The best operators launch with a plan B ready. "
            "Pivot speed separates winners from losers."
        ),
        "context": "backup_plan",
        "severity": "critical",
    },
    {
        "insight": (
            "Selection is not marriage. Set a 30-day evaluation window. "
            "If the product does not hit 75% of projected KPIs by day 30, "
            "activate your backup plan."
        ),
        "context": "time_bound",
        "severity": "important",
    },
    {
        "insight": (
            "The difference between a 70-score and 80-score product is often "
            "noise. The difference between a 40-score and 70-score product is "
            "signal. Do not over-optimize at the top."
        ),
        "context": "score_interpretation",
        "severity": "important",
    },
    {
        "insight": (
            "Your first product is a learning vehicle, not a retirement plan. "
            "Optimize for learning speed over profit maximization on your "
            "first selection."
        ),
        "context": "first_product",
        "severity": "moderate",
    },
    {
        "insight": (
            "Selecting a product is 10% of the work. Sourcing, listing, "
            "marketing, and fulfillment are the other 90%. Do not spend "
            "3 months selecting and 3 days executing."
        ),
        "context": "analysis_paralysis",
        "severity": "important",
    },
    {
        "insight": (
            "Risk is not just about the product — it is about your ability "
            "to recover. A $500 bet on a risky product is fine if you have "
            "$5000 in reserve. Calibrate risk to runway."
        ),
        "context": "risk_calibration",
        "severity": "critical",
    },
    {
        "insight": (
            "Past performance data is about markets, not about you. "
            "Your execution, marketing angle, and audience targeting can "
            "make a 'moderate' product perform like an 'excellent' one."
        ),
        "context": "personal_edge",
        "severity": "moderate",
    },
]

# --------------------------------------------------------------------------- #
#  Decision rationale templates
# --------------------------------------------------------------------------- #
RATIONALE_TEMPLATES: dict[str, str] = {
    "clear_winner": (
        "{product} selected as #1 pick. Scores highest across {dims_won} "
        "dimensions with {confidence}% confidence. Key strengths: {strengths}."
    ),
    "close_call": (
        "{product} selected over {runner_up} in a close decision. "
        "Margin of {gap:.1f} points. Deciding factor: {deciding_factor}."
    ),
    "risk_adjusted": (
        "{product} selected after risk adjustment. While {alt} scored higher "
        "raw, {product} has lower risk profile suitable for current constraints."
    ),
    "goal_optimized": (
        "{product} selected as best fit for {goal} goal. "
        "Goal-weighted score: {goal_score:.0f}/100."
    ),
}


def get_selection_insight(context: str | None = None) -> list[dict[str, str]]:
    """Return selection insights, optionally filtered by context.

    Args:
        context: Optional filter — 'execution', 'backup_plan',
                 'time_bound', 'score_interpretation', 'first_product',
                 'analysis_paralysis', 'risk_calibration', 'personal_edge'.

    Returns:
        List of matching insight dicts.
    """
    if context is None:
        return list(SELECTION_KNOWLEDGE)

    key = context.lower().replace(" ", "_").replace("-", "_")
    return [
        entry for entry in SELECTION_KNOWLEDGE
        if entry["context"] == key
    ]


def get_rationale_template(scenario: str) -> str:
    """Return a rationale template for a given selection scenario."""
    return RATIONALE_TEMPLATES.get(
        scenario,
        "{product} selected based on composite scoring and risk analysis.",
    )
