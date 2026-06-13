"""Canonical verdict + trend vocabularies for the empire-AGI loop.

Background
----------
W963-90 found that the empire-AGI substrate had TWO trend
vocabularies coexisting:

  Ladder A ("rising / falling / flat / no_data")
    Emitted by agi_earnings_summary._fleet_trend, which
    aggregates per-store agi_earnings_history trends into a
    fleet-wide verdict. Used by world-model + AI prompts.

  Ladder B ("improving / declining / flat / no_data")
    Emitted by agi_earnings_history.compute_trend, which
    classifies the verdict-rank delta across a window of
    persisted snapshots.

Both ladders carry the same SEMANTIC content (signal going
up / down / sideways / unknown) but use different tokens.
Downstream consumers (llm_action_proposer, agi_brief_diff)
were checking literal strings against one ladder, silently
missing the other.

Fix class, not instance
-----------------------
This module is the single source of truth for the two
vocabularies. New code should call ``is_declining(token)``
instead of ``trend == "falling"`` so adding a third vocab
later doesn't break the consumer.

Verdict rank (separate concern)
-------------------------------
The verdict rank ladder is also unified here so the W963-72
fix (attributed_loss=1 < organic_only=2) lives in ONE place
instead of being copied across agi_brief_diff,
agi_earnings_history, and agi_week_review.

Adding a new token
------------------
Add the token to the matching frozenset below + update the
matching IMPROVING/DECLINING/FLAT predicate. NEVER add a
new ladder without updating all consumers; the audit at
``shopai pattern-cb-audit`` (planned) will catch drift.
"""
from __future__ import annotations


# Verdict severity ladder (higher = healthier).
#   no_data:          0  idle / no signal
#   attributed_loss:  1  WORST -- AGI attributed + bleeding
#   organic_only:     2  neutral -- revenue exists but AGI
#                        not the cause
#   earning:          3  BEST -- AGI driving profit
# W963-72 invariant: attributed_loss is BELOW organic_only
# because the empire is ACTIVELY LOSING under AGI control
# vs merely failing to attribute. Don't flip.
VERDICT_RANK: dict[str, int] = {
    "no_data":         0,
    "attributed_loss": 1,
    "organic_only":    2,
    "earning":         3,
}


# Trend tokens that signal the empire's trajectory.
# DECLINING = downward direction (operator should worry).
DECLINING_TREND_TOKENS: frozenset[str] = frozenset({
    "falling",     # agi_earnings_summary ladder
    "declining",   # agi_earnings_history ladder
})

# IMPROVING = upward direction (operator may compound).
IMPROVING_TREND_TOKENS: frozenset[str] = frozenset({
    "rising",      # agi_earnings_summary ladder
    "improving",   # agi_earnings_history ladder
})

# FLAT = sideways. Both ladders converged on "flat".
FLAT_TREND_TOKENS: frozenset[str] = frozenset({
    "flat",
})


def is_declining(token: str | None) -> bool:
    """True if the token represents a downward trajectory
    across EITHER vocabulary. Use this instead of
    ``trend == "falling"`` so new ladders don't break the
    consumer silently."""
    if not token:
        return False
    return token in DECLINING_TREND_TOKENS


def is_improving(token: str | None) -> bool:
    """True if the token represents an upward trajectory."""
    if not token:
        return False
    return token in IMPROVING_TREND_TOKENS


def is_flat(token: str | None) -> bool:
    if not token:
        return False
    return token in FLAT_TREND_TOKENS


def normalize_trend(token: str | None) -> str:
    """Return a canonical 4-way classification: 'declining'
    / 'improving' / 'flat' / 'no_data'. Useful when a
    consumer wants to render a single label regardless of
    upstream vocabulary.

    Unknown tokens normalize to 'no_data' rather than
    raising -- the substrate is supposed to be lenient on
    untrusted input.
    """
    if is_declining(token):
        return "declining"
    if is_improving(token):
        return "improving"
    if is_flat(token):
        return "flat"
    return "no_data"
