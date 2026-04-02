"""Confidence domain knowledge — what seasoned operators know about certainty.

The gap between "we think this will work" and "this will work" is where
most product selection mistakes happen. These insights help calibrate
human expectations around algorithmic confidence.
"""
from __future__ import annotations

from typing import Any


# --------------------------------------------------------------------------- #
#  Core confidence truths
# --------------------------------------------------------------------------- #
CONFIDENCE_KNOWLEDGE: list[dict[str, str]] = [
    {
        "insight": (
            "Confidence of 60% means 40% chance you are wrong — size your "
            "bet accordingly. Do not invest $10k based on 60% confidence."
        ),
        "context": "risk_sizing",
        "severity": "critical",
    },
    {
        "insight": (
            "More data does not always help — sometimes you need different "
            "data. Ten demand signals saying the same thing add less than "
            "one profitability signal you are missing."
        ),
        "context": "data_quality",
        "severity": "important",
    },
    {
        "insight": (
            "When engines disagree, the negative signal is usually right. "
            "It is easier to find reasons something will work than reasons "
            "it will fail."
        ),
        "context": "signal_conflict",
        "severity": "critical",
    },
    {
        "insight": (
            "Historical accuracy decays fast. A model that was 75% accurate "
            "6 months ago might be 55% accurate today if the market shifted."
        ),
        "context": "historical_decay",
        "severity": "important",
    },
    {
        "insight": (
            "A narrow score gap between #1 and #2 means your confidence in "
            "picking #1 over #2 is low — even if overall confidence is high."
        ),
        "context": "score_gap",
        "severity": "moderate",
    },
    {
        "insight": (
            "Confidence is not binary. A 45% confidence product can still "
            "succeed — it just means you should test with smaller inventory "
            "and tighter stop-losses."
        ),
        "context": "decision_sizing",
        "severity": "important",
    },
    {
        "insight": (
            "The most dangerous confidence is 70-80%. High enough to feel "
            "safe, not high enough to actually be safe. This is where "
            "overcommitment happens."
        ),
        "context": "overconfidence",
        "severity": "critical",
    },
    {
        "insight": (
            "Perfect data leads to paralysis. Set a threshold and act. "
            "You learn more from launching at 60% confidence than from "
            "waiting for 90% confidence."
        ),
        "context": "action_bias",
        "severity": "moderate",
    },
]

# --------------------------------------------------------------------------- #
#  Confidence-to-action mapping wisdom
# --------------------------------------------------------------------------- #
CONFIDENCE_ACTION_WISDOM: dict[str, str] = {
    "low": (
        "Low confidence means you are guessing. Small test order only. "
        "Validate with real customers before scaling."
    ),
    "medium": (
        "Medium confidence is actionable but not comfortable. Proceed "
        "with monitoring — set a 2-week review checkpoint."
    ),
    "high": (
        "High confidence means the data aligns. Move quickly but keep "
        "your backup product ready. Markets shift."
    ),
}


def get_confidence_insight(context: str | None = None) -> list[dict[str, str]]:
    """Return confidence insights, optionally filtered by context.

    Args:
        context: Optional filter — 'risk_sizing', 'data_quality',
                 'signal_conflict', 'historical_decay', 'score_gap',
                 'decision_sizing', 'overconfidence', 'action_bias'.

    Returns:
        List of matching insight dicts with keys: insight, context, severity.
    """
    if context is None:
        return list(CONFIDENCE_KNOWLEDGE)

    key = context.lower().replace(" ", "_").replace("-", "_")
    return [
        entry for entry in CONFIDENCE_KNOWLEDGE
        if entry["context"] == key
    ]


def get_action_wisdom(confidence_level: str) -> str:
    """Return decision-making wisdom for a given confidence level."""
    normalized = confidence_level.lower().strip()
    return CONFIDENCE_ACTION_WISDOM.get(
        normalized,
        "Unknown confidence level. Treat as low confidence — proceed cautiously.",
    )
