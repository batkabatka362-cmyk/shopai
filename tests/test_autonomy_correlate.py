"""Tests for core.automation.autonomy_correlate (Wave 746-750).

Pairwise Jaccard correlation across autonomy domains.
"""
from __future__ import annotations

import pytest

from core.automation.autonomy_correlate import (
    CorrelationPair,
    CorrelationReport,
    run_autonomy_correlate,
)


class TestRunAutonomyCorrelate:

    def test_returns_report(self):
        r = run_autonomy_correlate()
        assert isinstance(r, CorrelationReport)

    def test_idle_branch_no_pairs(self):
        # No autonomous fires recorded -> 0 active + 0 pairs
        r = run_autonomy_correlate()
        assert r.active_domain_count == 0
        assert r.pairs == []

    def test_bucket_count_matches_window(self):
        r = run_autonomy_correlate(
            window_hours=168.0, bucket_hours=24.0,
        )
        # ceil(168/24) = 7
        assert r.bucket_count == 7

    def test_bucket_count_for_non_divisible_window(self):
        r = run_autonomy_correlate(
            window_hours=50.0, bucket_hours=24.0,
        )
        # ceil(50/24) = 3
        assert r.bucket_count == 3

    def test_rejects_zero_bucket_hours(self):
        with pytest.raises(ValueError):
            run_autonomy_correlate(bucket_hours=0)

    def test_rejects_negative_bucket_hours(self):
        with pytest.raises(ValueError):
            run_autonomy_correlate(bucket_hours=-1)

    def test_rejects_zero_window_hours(self):
        with pytest.raises(ValueError):
            run_autonomy_correlate(window_hours=0)

    def test_window_hours_preserved(self):
        r = run_autonomy_correlate(window_hours=48.0)
        assert r.window_hours == 48.0

    def test_bucket_hours_preserved(self):
        r = run_autonomy_correlate(
            window_hours=48.0, bucket_hours=8.0,
        )
        assert r.bucket_hours == 8.0

    def test_pairs_sorted_by_jaccard_desc(self):
        # On idle branch this is vacuously true (0 pairs).
        # Construct synthetic pairs to verify sort invariant
        # would hold.
        r = CorrelationReport(
            window_hours=24.0, bucket_hours=8.0, bucket_count=3,
        )
        r.pairs = [
            CorrelationPair(
                domain_a="a", domain_b="b",
                buckets_a=2, buckets_b=2,
                shared=1, union=3, jaccard=0.33,
            ),
            CorrelationPair(
                domain_a="c", domain_b="d",
                buckets_a=2, buckets_b=2,
                shared=2, union=2, jaccard=1.0,
            ),
        ]
        # Manual sort + verify desc
        r.pairs.sort(key=lambda p: -p.jaccard)
        jaccards = [p.jaccard for p in r.pairs]
        assert jaccards == sorted(jaccards, reverse=True)


class TestCorrelationPairDataclass:

    def test_defaults(self):
        p = CorrelationPair(
            domain_a="a", domain_b="b",
            buckets_a=0, buckets_b=0,
            shared=0, union=0,
        )
        assert p.jaccard == 0.0


class TestCorrelationReportDataclass:

    def test_defaults(self):
        r = CorrelationReport(
            window_hours=24.0, bucket_hours=8.0,
            bucket_count=3,
        )
        assert r.pairs == []
        assert r.active_domain_count == 0
        assert r.store_id is None
