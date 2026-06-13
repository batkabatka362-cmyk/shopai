"""Tests for engines._attribution_delta."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engines._attribution_delta import (
    AttributionDelta,
    ClusterDelta,
    EngineDelta,
    compute_delta,
    latest_delta,
    propagate_alerts_to_bus,
)
from engines._attribution_snapshot import AttributionSnapshot


def _snap(
    *,
    sid: str,
    captured_at: float,
    attributed: float = 0.0,
    total_revenue: float = 0.0,
    per_cluster: list[dict] | None = None,
    per_engine: list[dict] | None = None,
) -> AttributionSnapshot:
    return AttributionSnapshot(
        snapshot_id=sid,
        captured_at=captured_at,
        window_hours=168.0,
        store_id=None,
        total_orders_in_window=0,
        total_revenue_in_window=total_revenue,
        attributed_revenue=attributed,
        attribution_rate=0.0,
        per_cluster=per_cluster or [],
        per_engine=per_engine or [],
    )


class TestClusterDeltaProperties:

    def test_revenue_delta(self):
        cd = ClusterDelta(
            cluster="x",
            prior_revenue=100.0, latest_revenue=150.0,
            prior_orders=1, latest_orders=2,
        )
        assert cd.revenue_delta == 50.0

    def test_revenue_delta_pct_positive(self):
        cd = ClusterDelta(
            cluster="x",
            prior_revenue=100.0, latest_revenue=150.0,
            prior_orders=1, latest_orders=2,
        )
        assert cd.revenue_delta_pct == 0.5

    def test_revenue_delta_pct_none_when_prior_zero(self):
        cd = ClusterDelta(
            cluster="x",
            prior_revenue=0.0, latest_revenue=150.0,
            prior_orders=0, latest_orders=2,
        )
        assert cd.revenue_delta_pct is None

    def test_direction_up(self):
        cd = ClusterDelta(
            cluster="x",
            prior_revenue=100.0, latest_revenue=150.0,
            prior_orders=1, latest_orders=2,
        )
        assert cd.direction == "up"

    def test_direction_down(self):
        cd = ClusterDelta(
            cluster="x",
            prior_revenue=150.0, latest_revenue=100.0,
            prior_orders=2, latest_orders=1,
        )
        assert cd.direction == "down"

    def test_direction_new(self):
        cd = ClusterDelta(
            cluster="x",
            prior_revenue=0.0, latest_revenue=100.0,
            prior_orders=0, latest_orders=1,
        )
        assert cd.direction == "new"

    def test_direction_dropped(self):
        cd = ClusterDelta(
            cluster="x",
            prior_revenue=100.0, latest_revenue=0.0,
            prior_orders=1, latest_orders=0,
        )
        assert cd.direction == "dropped"

    def test_direction_flat_both_zero(self):
        cd = ClusterDelta(
            cluster="x",
            prior_revenue=0.0, latest_revenue=0.0,
            prior_orders=0, latest_orders=0,
        )
        assert cd.direction == "flat"


class TestComputeDelta:

    def test_overall_delta_sums(self):
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=250.0,
        )
        d = compute_delta(prior, latest)
        assert d.overall_revenue_delta == 150.0
        assert d.overall_revenue_delta_pct == 1.5

    def test_per_cluster_diff(self):
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 5},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=250.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 250.0,
                 "attributed_orders": 10},
            ],
        )
        d = compute_delta(prior, latest)
        assert len(d.per_cluster) == 1
        cd = d.per_cluster[0]
        assert cd.cluster == "retention"
        assert cd.revenue_delta == 150.0
        assert cd.direction == "up"

    def test_cluster_in_latest_only(self):
        """Cluster that only appears in the latest snapshot is
        marked 'new'."""
        prior = _snap(sid="a", captured_at=1.0)
        latest = _snap(
            sid="b", captured_at=2.0, attributed=50.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 50.0,
                 "attributed_orders": 2},
            ],
        )
        d = compute_delta(prior, latest)
        assert len(d.per_cluster) == 1
        assert d.per_cluster[0].direction == "new"

    def test_cluster_in_prior_only(self):
        """Cluster that disappears is marked 'dropped'."""
        prior = _snap(
            sid="a", captured_at=1.0, attributed=50.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 50.0,
                 "attributed_orders": 2},
            ],
        )
        latest = _snap(sid="b", captured_at=2.0)
        d = compute_delta(prior, latest)
        assert len(d.per_cluster) == 1
        assert d.per_cluster[0].direction == "dropped"


class TestRegressionAlerts:

    def test_alert_fires_on_25_pct_drop(self):
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 5},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=50.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 50.0,
                 "attributed_orders": 3},
            ],
        )
        d = compute_delta(prior, latest)
        assert d.has_alerts
        assert d.alerts[0].scope == "cluster"
        assert d.alerts[0].name == "retention"
        assert d.alerts[0].delta_pct == -0.5

    def test_alert_suppressed_under_min_orders(self):
        """Single-order drops shouldn't fire alerts."""
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 1},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=50.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 50.0,
                 "attributed_orders": 1},
            ],
        )
        d = compute_delta(prior, latest)
        assert not d.has_alerts

    def test_alert_not_fired_on_small_drop(self):
        """5% drop is below the default 25% threshold."""
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 5},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=95.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 95.0,
                 "attributed_orders": 5},
            ],
        )
        d = compute_delta(prior, latest)
        assert not d.has_alerts

    def test_alert_engine_scope(self):
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
            per_engine=[
                {"engine": "loyalty",
                 "cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 5},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=20.0,
            per_engine=[
                {"engine": "loyalty",
                 "cluster": "retention",
                 "attributed_revenue": 20.0,
                 "attributed_orders": 3},
            ],
        )
        d = compute_delta(prior, latest)
        engine_alerts = [a for a in d.alerts if a.scope == "engine"]
        assert len(engine_alerts) == 1
        assert engine_alerts[0].name == "loyalty"

    def test_custom_threshold(self):
        """Threshold = 0.10 (10%): a 15% drop should now fire."""
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 5},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=85.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 85.0,
                 "attributed_orders": 5},
            ],
        )
        d = compute_delta(prior, latest, regression_pct=0.10)
        assert d.has_alerts


class TestSortOrder:

    def test_per_cluster_sorted_by_abs_delta_desc(self):
        prior = _snap(
            sid="a", captured_at=1.0, attributed=200.0,
            per_cluster=[
                {"cluster": "small_change",
                 "attributed_revenue": 100.0, "attributed_orders": 5},
                {"cluster": "big_change",
                 "attributed_revenue": 100.0, "attributed_orders": 5},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=250.0,
            per_cluster=[
                {"cluster": "small_change",
                 "attributed_revenue": 110.0, "attributed_orders": 5},
                {"cluster": "big_change",
                 "attributed_revenue": 140.0, "attributed_orders": 7},
            ],
        )
        d = compute_delta(prior, latest)
        assert d.per_cluster[0].cluster == "big_change"


class TestPropagateAlertsToBus:

    def test_no_alerts_emits_zero(self):
        delta = AttributionDelta(
            prior_snapshot_id="a", latest_snapshot_id="b",
            prior_captured_at=1.0, latest_captured_at=2.0,
            prior_total_revenue=0.0, latest_total_revenue=0.0,
            prior_attributed_revenue=0.0,
            latest_attributed_revenue=0.0,
        )
        assert propagate_alerts_to_bus(delta) == 0

    def test_cluster_alert_emits_one(self, monkeypatch, tmp_path):
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        from engines._cluster_bus import clear_bus, subscribe_events
        clear_bus()
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 5},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=50.0,
            per_cluster=[
                {"cluster": "retention",
                 "attributed_revenue": 50.0,
                 "attributed_orders": 3},
            ],
        )
        delta = compute_delta(prior, latest)
        n = propagate_alerts_to_bus(delta)
        assert n == 1
        events = subscribe_events(window_hours=1.0)
        assert any(
            e.emitter_cluster == "retention"
            and e.topic == "revenue_regression"
            for e in events
        )

    def test_engine_alert_emits_to_engine_cluster(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        from engines._cluster_bus import clear_bus, subscribe_events
        clear_bus()
        prior = _snap(
            sid="a", captured_at=1.0, attributed=100.0,
            per_engine=[
                {"engine": "loyalty",
                 "cluster": "retention",
                 "attributed_revenue": 100.0,
                 "attributed_orders": 5},
            ],
        )
        latest = _snap(
            sid="b", captured_at=2.0, attributed=20.0,
            per_engine=[
                {"engine": "loyalty",
                 "cluster": "retention",
                 "attributed_revenue": 20.0,
                 "attributed_orders": 3},
            ],
        )
        delta = compute_delta(prior, latest)
        # delta has engine alert; engine cluster is retention.
        # propagate should emit one event tagged with retention.
        n = propagate_alerts_to_bus(delta)
        assert n >= 1
        events = subscribe_events(window_hours=1.0)
        emitter_clusters = {e.emitter_cluster for e in events}
        assert "retention" in emitter_clusters


class TestSignalMapping:

    def test_regression_event_rolls_up_in_cross_cluster_signals(
        self, monkeypatch, tmp_path,
    ):
        """Bus's cross_cluster_signals maps revenue_regression
        events to recent_regression_count per emitter cluster."""
        monkeypatch.setenv("SHOPAI_DATA_DIR", str(tmp_path))
        from engines._cluster_bus import (
            clear_bus, emit_event, cross_cluster_signals,
        )
        clear_bus()
        emit_event(
            emitter_cluster="retention",
            topic="revenue_regression",
            payload={"delta_pct": -0.5},
        )
        emit_event(
            emitter_cluster="retention",
            topic="revenue_regression",
            payload={"delta_pct": -0.6},
        )
        signals = cross_cluster_signals(window_hours=1.0)
        assert "retention" in signals
        assert signals["retention"]["recent_regression_count"] == 2


class TestLatestDelta:

    def test_returns_none_when_less_than_2_snapshots(self):
        with patch(
            "engines._attribution_delta.recent_snapshots",
            return_value=[],
        ):
            assert latest_delta() is None
        with patch(
            "engines._attribution_delta.recent_snapshots",
            return_value=[_snap(sid="a", captured_at=1.0)],
        ):
            assert latest_delta() is None

    def test_diffs_top_two(self):
        a = _snap(sid="a", captured_at=1.0, attributed=100.0)
        b = _snap(sid="b", captured_at=2.0, attributed=200.0)
        # recent_snapshots returns newest first -> [b, a]
        with patch(
            "engines._attribution_delta.recent_snapshots",
            return_value=[b, a],
        ):
            d = latest_delta()
        assert d is not None
        assert d.prior_snapshot_id == "a"
        assert d.latest_snapshot_id == "b"
        assert d.overall_revenue_delta == 100.0
