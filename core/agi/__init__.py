"""core.agi -- shared substrate primitives for the empire-AGI loop.

Currently houses:
  verdict_vocabulary  -- canonical verdict + trend ladders
                         shared by agi_earnings_summary,
                         agi_earnings_history, agi_brief_diff,
                         agi_week_review, llm_action_proposer.
  persistence         -- Pattern J guard + atomic JSON write
                         + tolerant JSON load, shared by 24+
                         engines (W963-92).

Adding new substrate? If the value/helper is consumed by 2+
engines, hoist it here so the implementation stays consistent.
"""
from .persistence import (
    atomic_write_json,
    atomic_write_text,
    is_test_environment,
    load_json_dict,
    load_json_list,
)
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
    # verdict_vocabulary
    "VERDICT_RANK",
    "DECLINING_TREND_TOKENS",
    "IMPROVING_TREND_TOKENS",
    "FLAT_TREND_TOKENS",
    "is_declining",
    "is_improving",
    "is_flat",
    "normalize_trend",
    # persistence
    "is_test_environment",
    "atomic_write_json",
    "atomic_write_text",
    "load_json_list",
    "load_json_dict",
]
