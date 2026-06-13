"""Tests for core.agi.verdict_vocabulary — W963-91."""
from __future__ import annotations

import pytest

from core.agi.verdict_vocabulary import (
    DECLINING_TREND_TOKENS,
    FLAT_TREND_TOKENS,
    IMPROVING_TREND_TOKENS,
    VERDICT_RANK,
    is_declining,
    is_flat,
    is_improving,
    normalize_trend,
)


# ── VERDICT_RANK invariant ────────────────────────────────


class TestVerdictRank:
    def test_w963_72_invariant(self):
        """attributed_loss MUST sit below organic_only.
        Don't flip without revisiting W963-72 reasoning."""
        assert (
            VERDICT_RANK["attributed_loss"]
            < VERDICT_RANK["organic_only"]
        )

    def test_full_ladder_order(self):
        assert VERDICT_RANK["no_data"] == 0
        assert VERDICT_RANK["attributed_loss"] == 1
        assert VERDICT_RANK["organic_only"] == 2
        assert VERDICT_RANK["earning"] == 3

    def test_all_four_distinct(self):
        assert len(set(VERDICT_RANK.values())) == 4


# ── trend predicates ──────────────────────────────────────


class TestIsDeclining:
    def test_falling_token(self):
        # agi_earnings_summary vocabulary
        assert is_declining("falling") is True

    def test_declining_token(self):
        # agi_earnings_history vocabulary
        assert is_declining("declining") is True

    def test_rising_false(self):
        assert is_declining("rising") is False

    def test_improving_false(self):
        assert is_declining("improving") is False

    def test_flat_false(self):
        assert is_declining("flat") is False

    def test_no_data_false(self):
        assert is_declining("no_data") is False

    def test_none_false(self):
        assert is_declining(None) is False

    def test_empty_false(self):
        assert is_declining("") is False

    def test_unknown_false(self):
        # Lenient: unknown tokens DON'T flag.
        assert is_declining("garbage") is False


class TestIsImproving:
    def test_rising_token(self):
        assert is_improving("rising") is True

    def test_improving_token(self):
        assert is_improving("improving") is True

    def test_falling_false(self):
        assert is_improving("falling") is False

    def test_declining_false(self):
        assert is_improving("declining") is False

    def test_flat_false(self):
        assert is_improving("flat") is False

    def test_none_false(self):
        assert is_improving(None) is False


class TestIsFlat:
    def test_flat_token(self):
        assert is_flat("flat") is True

    def test_rising_false(self):
        assert is_flat("rising") is False

    def test_none_false(self):
        assert is_flat(None) is False


# ── normalize_trend ───────────────────────────────────────


class TestNormalizeTrend:
    @pytest.mark.parametrize("input_token", [
        "falling", "declining",
    ])
    def test_declining_tokens_normalize(self, input_token):
        assert normalize_trend(input_token) == "declining"

    @pytest.mark.parametrize("input_token", [
        "rising", "improving",
    ])
    def test_improving_tokens_normalize(self, input_token):
        assert normalize_trend(input_token) == "improving"

    def test_flat(self):
        assert normalize_trend("flat") == "flat"

    def test_unknown_to_no_data(self):
        assert normalize_trend("garbage") == "no_data"

    def test_none_to_no_data(self):
        assert normalize_trend(None) == "no_data"


# ── frozen set guards (caller may not mutate) ─────────────


class TestFrozenSets:
    def test_declining_is_frozenset(self):
        assert isinstance(
            DECLINING_TREND_TOKENS, frozenset,
        )

    def test_improving_is_frozenset(self):
        assert isinstance(
            IMPROVING_TREND_TOKENS, frozenset,
        )

    def test_flat_is_frozenset(self):
        assert isinstance(FLAT_TREND_TOKENS, frozenset)

    def test_no_overlap_between_directions(self):
        """A token must not be both declining + improving."""
        assert not (
            DECLINING_TREND_TOKENS & IMPROVING_TREND_TOKENS
        )

    def test_flat_disjoint_from_directional(self):
        assert not (FLAT_TREND_TOKENS & DECLINING_TREND_TOKENS)
        assert not (FLAT_TREND_TOKENS & IMPROVING_TREND_TOKENS)


# ── Consumer migration sanity ──────────────────────────────


class TestDownstreamMigration:
    def test_agi_brief_diff_uses_canonical(self):
        from engines.agi_brief_diff.differ import (
            _VERDICT_RANK,
        )
        assert _VERDICT_RANK is VERDICT_RANK

    def test_agi_earnings_history_uses_canonical(self):
        from engines.agi_earnings_history.store import (
            _VERDICT_RANK,
        )
        assert _VERDICT_RANK is VERDICT_RANK

    def test_agi_week_review_uses_canonical(self):
        from engines.agi_week_review.reviewer import (
            _VERDICT_RANK,
        )
        assert _VERDICT_RANK is VERDICT_RANK
