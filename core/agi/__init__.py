"""core.agi -- shared substrate primitives for the empire-AGI loop.

Currently houses:
  verdict_vocabulary  -- canonical verdict + trend ladders
                         shared by agi_earnings_summary,
                         agi_earnings_history, agi_brief_diff,
                         agi_week_review, llm_action_proposer.

Adding new substrate? If the value is consumed by 2+ engines,
hoist it here so the vocabulary stays consistent.
"""
from .verdict_vocabulary import (
    VERDICT_RANK,
    DECLINING_TREND_TOKENS,
    IMPROVING_TREND_TOKENS,
    FLAT_TREND_TOKENS,
    is_declining,
    is_improving,
    is_flat,
    normalize_trend,
)

__all__ = [
    "VERDICT_RANK",
    "DECLINING_TREND_TOKENS",
    "IMPROVING_TREND_TOKENS",
    "FLAT_TREND_TOKENS",
    "is_declining",
    "is_improving",
    "is_flat",
    "normalize_trend",
]
