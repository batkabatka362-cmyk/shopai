"""Tests for ``core.approval.outcome_aggregator`` — the shared
polarity / revenue rollup that future CLI handlers can adopt.

Robustness contract: any caller passing the result of
``ApprovalQueue.get_outcomes(action_id)`` should get back a
valid ``OutcomeStats`` instance, even when the row data is
malformed or missing fields. The aggregator never raises.
"""
from __future__ import annotations

import pytest

from core.approval.outcome_aggregator import (
    OutcomeStats,
    aggregate_outcomes,
)


# ─── Empty / None inputs ─────────────────────────────────────


class TestEmptyInput:

    def test_empty_list_returns_zero_stats(self):
        s = aggregate_outcomes([])
        assert s.total == 0
        assert s.positive == 0
        assert s.negative == 0
        assert s.neutral == 0
        assert s.other == 0
        assert s.revenue == 0.0
        assert s.outcome_score is None

    def test_none_input_treated_as_empty(self):
        s = aggregate_outcomes(None)
        assert s.total == 0
        assert s.outcome_score is None


# ─── Polarity counting ───────────────────────────────────────


class TestPolarityCounting:

    def test_three_flavors_counted_separately(self):
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {}},
            {"polarity": "positive", "metrics": {}},
            {"polarity": "negative", "metrics": {}},
            {"polarity": "neutral", "metrics": {}},
        ])
        assert s.total == 4
        assert s.positive == 2
        assert s.negative == 1
        assert s.neutral == 1
        assert s.other == 0

    def test_missing_polarity_counts_as_other(self):
        s = aggregate_outcomes([
            {"metrics": {}},  # no polarity key
            {"polarity": None, "metrics": {}},  # None polarity
            {"polarity": "unknown_flavor", "metrics": {}},
        ])
        assert s.total == 3
        assert s.positive == 0
        assert s.other == 3

    def test_non_dict_entry_counts_as_other(self):
        """A list element that isn't a dict (None, string, etc.)
        shouldn't crash the rollup; it gets counted as ``other``."""
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {}},
            None,  # not a dict
            "garbage",
            42,
        ])
        assert s.total == 4
        assert s.positive == 1
        assert s.other == 3


# ─── Revenue summing ─────────────────────────────────────────


class TestRevenueSumming:

    def test_revenue_sums_across_rows(self):
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {"revenue": 100.0}},
            {"polarity": "positive", "metrics": {"revenue": 50.0}},
            {"polarity": "negative", "metrics": {"revenue": -10.0}},
        ])
        # 100 + 50 + (-10) = 140
        assert s.revenue == 140.0

    def test_missing_metrics_dict_treated_as_zero(self):
        s = aggregate_outcomes([
            {"polarity": "positive"},  # no metrics key
            {"polarity": "negative", "metrics": None},
            {"polarity": "neutral", "metrics": "not a dict"},
        ])
        assert s.total == 3
        assert s.revenue == 0.0

    def test_missing_revenue_key_treated_as_zero(self):
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {"other_key": 999}},
        ])
        assert s.revenue == 0.0

    def test_non_numeric_revenue_skipped(self):
        """Non-numeric revenue values shouldn't crash; they're
        silently dropped from the sum."""
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {"revenue": "not a number"}},
            {"polarity": "positive", "metrics": {"revenue": None}},
            {"polarity": "positive", "metrics": {"revenue": [1, 2]}},
            {"polarity": "positive", "metrics": {"revenue": 25.0}},
        ])
        assert s.total == 4
        # Only the 25.0 contributes.
        assert s.revenue == 25.0


# ─── outcome_score computation ───────────────────────────────


class TestOutcomeScore:

    def test_all_positive_gives_score_1(self):
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {}},
            {"polarity": "positive", "metrics": {}},
        ])
        assert s.outcome_score == 1.0

    def test_all_negative_gives_score_0(self):
        s = aggregate_outcomes([
            {"polarity": "negative", "metrics": {}},
            {"polarity": "negative", "metrics": {}},
        ])
        assert s.outcome_score == 0.0

    def test_mixed_gives_fraction(self):
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {}},
            {"polarity": "positive", "metrics": {}},
            {"polarity": "negative", "metrics": {}},
        ])
        # 2 / (2 + 1) = 0.6667
        assert s.outcome_score == pytest.approx(2 / 3)

    def test_only_neutral_gives_none(self):
        """Neutral events alone (no positive / negative) →
        score is None, not divide-by-zero."""
        s = aggregate_outcomes([
            {"polarity": "neutral", "metrics": {}},
            {"polarity": "neutral", "metrics": {}},
        ])
        assert s.outcome_score is None

    def test_only_other_gives_none(self):
        s = aggregate_outcomes([
            {"polarity": "garbage", "metrics": {}},
        ])
        assert s.outcome_score is None


# ─── OutcomeStats interface ──────────────────────────────────


class TestOutcomeStatsInterface:

    def test_as_dict_round_trip(self):
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {"revenue": 50.0}},
            {"polarity": "negative", "metrics": {}},
        ])
        d = s.as_dict()
        assert d["total"] == 2
        assert d["positive"] == 1
        assert d["negative"] == 1
        assert d["revenue"] == 50.0
        assert d["outcome_score"] == 0.5

    def test_outcome_score_none_survives_as_dict(self):
        """None should survive as None (not coerced) for JSON
        envelope callers."""
        s = aggregate_outcomes([])
        d = s.as_dict()
        assert d["outcome_score"] is None

    def test_outcome_stats_is_immutable(self):
        """Dataclass is frozen → caller can't mutate the
        returned stats by accident."""
        s = aggregate_outcomes([
            {"polarity": "positive", "metrics": {}},
        ])
        with pytest.raises(Exception):
            s.positive = 999  # type: ignore[misc]


# ─── Iterator support ────────────────────────────────────────


class TestIterableSupport:

    def test_generator_input_works(self):
        """The signature accepts ``Iterable``, not just list."""
        def gen():
            yield {"polarity": "positive", "metrics": {"revenue": 10.0}}
            yield {"polarity": "negative", "metrics": {}}

        s = aggregate_outcomes(gen())
        assert s.total == 2
        assert s.revenue == 10.0
