"""Tests for engines._outcome_window."""
from __future__ import annotations

import time

from engines._outcome_window import (
    OutcomeWindow,
    engine_outcomes_window,
    cluster_outcomes_window,
    fleet_outcomes_window,
)


class TestOutcomeWindow:

    def test_positive_ratio(self):
        w = OutcomeWindow(
            scope="engine:X",
            window_hours=24.0,
            cutoff_at=time.time(),
            positive_count=7,
            negative_count=3,
            neutral_count=2,
        )
        # ratio = positive / (positive + negative) = 7/10 = 0.7
        assert w.positive_ratio == 0.7

    def test_total_outcomes(self):
        w = OutcomeWindow(
            scope="engine:X",
            window_hours=24.0,
            cutoff_at=time.time(),
            positive_count=7,
            negative_count=3,
            neutral_count=2,
        )
        assert w.total_outcomes == 12

    def test_trending_positive(self):
        w = OutcomeWindow(
            scope="engine:X",
            window_hours=24.0,
            cutoff_at=time.time(),
            positive_count=8, negative_count=2,
        )
        assert w.is_trending_positive is True
        assert w.is_trending_negative is False

    def test_trending_negative(self):
        w = OutcomeWindow(
            scope="engine:X",
            window_hours=24.0,
            cutoff_at=time.time(),
            positive_count=2, negative_count=8,
        )
        assert w.is_trending_negative is True
        assert w.is_trending_positive is False

    def test_no_trend_with_low_samples(self):
        w = OutcomeWindow(
            scope="engine:X",
            window_hours=24.0,
            cutoff_at=time.time(),
            positive_count=2, negative_count=0,
        )
        # only 2 outcomes -> not enough to declare a trend
        assert w.is_trending_positive is False
        assert w.is_trending_negative is False


class TestEngineWindow:

    def test_unknown_engine_returns_empty(self):
        w = engine_outcomes_window(
            "this-engine-does-not-exist-12345",
            window_hours=24.0,
        )
        assert w.total_outcomes == 0
        assert w.total_revenue == 0.0

    def test_with_store_filter(self):
        w = engine_outcomes_window(
            "loyalty",
            window_hours=24.0,
            store_id="store-A",
        )
        # No real outcomes in test DB -> 0
        assert w.total_outcomes == 0
        assert "store-A" in w.scope


class TestClusterWindow:

    def test_known_cluster_returns_window(self):
        w = cluster_outcomes_window(
            "retention", window_hours=168.0,
        )
        assert w.scope == "cluster:retention"
        assert w.window_hours == 168.0

    def test_unknown_cluster_returns_empty(self):
        w = cluster_outcomes_window(
            "does-not-exist", window_hours=24.0,
        )
        assert w.total_outcomes == 0


class TestFleetWindow:

    def test_fleet_returns_all_clusters(self):
        windows = fleet_outcomes_window(window_hours=24.0)
        # 10 clusters expected
        assert len(windows) == 10
        scopes = {w.scope for w in windows}
        assert "cluster:retention" in scopes
        assert "cluster:pricing" in scopes
