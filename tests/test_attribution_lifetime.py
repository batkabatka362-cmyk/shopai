"""Tests for engines._attribution_lifetime."""
from __future__ import annotations

from unittest.mock import patch

from engines._attribution_lifetime import (
    LifetimeRollup,
    lifetime_per_cluster,
    lifetime_rollup,
)
from engines._attribution_snapshot import AttributionSnapshot


def _snap(*, sid, captured_at, attributed=0.0, per_cluster=None):
    return AttributionSnapshot(
        snapshot_id=sid,
        captured_at=captured_at,
        window_hours=168.0,
        store_id=None,
        attributed_revenue=attributed,
        per_cluster=per_cluster or [],
    )


def _cluster_row(cluster, revenue, orders=1):
    return {
        "cluster": cluster,
        "attributed_revenue": revenue,
        "attributed_orders": orders,
    }


class TestLifetimeRollup:

    def test_empty_when_fewer_than_two_snapshots(self):
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=[],
        ):
            assert lifetime_rollup().cycle_pairs_seen == 0
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=[_snap(sid="a", captured_at=1.0)],
        ):
            assert lifetime_rollup().cycle_pairs_seen == 0

    def test_pure_growth(self):
        """Three snapshots, each higher than the last: lifetime
        added = sum of positive deltas."""
        snaps = [
            _snap(sid="c", captured_at=3.0, attributed=500.0),
            _snap(sid="b", captured_at=2.0, attributed=200.0),
            _snap(sid="a", captured_at=1.0, attributed=100.0),
        ]  # newest first
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=snaps,
        ):
            r = lifetime_rollup()
        # Deltas: (c-b)=300, (b-a)=100 -> total_added = 400
        assert r.cycle_pairs_seen == 2
        assert r.total_added == 400.0
        assert r.total_lost == 0.0
        assert r.net == 400.0
        assert r.largest_gain["amount"] == 300.0

    def test_pure_decline_no_growth(self):
        snaps = [
            _snap(sid="c", captured_at=3.0, attributed=50.0),
            _snap(sid="b", captured_at=2.0, attributed=200.0),
            _snap(sid="a", captured_at=1.0, attributed=500.0),
        ]
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=snaps,
        ):
            r = lifetime_rollup()
        # All deltas negative; no positive additions
        assert r.total_added == 0.0
        # 150 + 300 lost
        assert r.total_lost == 450.0
        assert r.net == -450.0

    def test_mixed_separately_tracks_gain_and_loss(self):
        snaps = [
            _snap(sid="d", captured_at=4.0, attributed=200.0),
            _snap(sid="c", captured_at=3.0, attributed=50.0),
            _snap(sid="b", captured_at=2.0, attributed=300.0),
            _snap(sid="a", captured_at=1.0, attributed=100.0),
        ]
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=snaps,
        ):
            r = lifetime_rollup()
        # Deltas: (d-c)=+150, (c-b)=-250, (b-a)=+200
        assert r.total_added == 350.0
        assert r.total_lost == 250.0
        assert r.net == 100.0
        # Largest gain = 200 (b vs a)
        assert r.largest_gain["amount"] == 200.0
        # Largest loss = 250
        assert r.largest_loss["amount"] == 250.0

    def test_flat_cycles_dont_count(self):
        snaps = [
            _snap(sid="c", captured_at=3.0, attributed=100.0),
            _snap(sid="b", captured_at=2.0, attributed=100.0),
            _snap(sid="a", captured_at=1.0, attributed=100.0),
        ]
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=snaps,
        ):
            r = lifetime_rollup()
        # All deltas = 0
        assert r.total_added == 0.0
        assert r.total_lost == 0.0
        # Cycle pairs counted even when zero
        assert r.cycle_pairs_seen == 2


class TestLifetimePerCluster:

    def test_empty_when_fewer_than_two_snapshots(self):
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=[],
        ):
            assert lifetime_per_cluster() == []

    def test_aggregates_gain_and_loss_per_cluster(self):
        snaps = [
            _snap(
                sid="c", captured_at=3.0,
                per_cluster=[
                    _cluster_row("retention", 500.0),
                    _cluster_row("pricing", 100.0),
                ],
            ),
            _snap(
                sid="b", captured_at=2.0,
                per_cluster=[
                    _cluster_row("retention", 300.0),
                    _cluster_row("pricing", 200.0),
                ],
            ),
            _snap(
                sid="a", captured_at=1.0,
                per_cluster=[
                    _cluster_row("retention", 100.0),
                    _cluster_row("pricing", 100.0),
                ],
            ),
        ]
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=snaps,
        ):
            rows = lifetime_per_cluster()
        per_c = {r["cluster"]: r for r in rows}
        # retention: +200 (b vs a), +200 (c vs b) -> +400
        assert per_c["retention"]["total_added"] == 400.0
        assert per_c["retention"]["total_lost"] == 0.0
        assert per_c["retention"]["net"] == 400.0
        # pricing: +100 (b vs a), -100 (c vs b) -> 0 net
        assert per_c["pricing"]["total_added"] == 100.0
        assert per_c["pricing"]["total_lost"] == 100.0
        assert per_c["pricing"]["net"] == 0.0

    def test_sorted_by_net_desc(self):
        snaps = [
            _snap(
                sid="c", captured_at=3.0,
                per_cluster=[
                    _cluster_row("small_winner", 110.0),
                    _cluster_row("big_winner", 1000.0),
                ],
            ),
            _snap(
                sid="b", captured_at=2.0,
                per_cluster=[
                    _cluster_row("small_winner", 100.0),
                    _cluster_row("big_winner", 100.0),
                ],
            ),
        ]
        with patch(
            "engines._attribution_snapshot.recent_snapshots",
            return_value=snaps,
        ):
            rows = lifetime_per_cluster()
        # big_winner first, small_winner second
        assert rows[0]["cluster"] == "big_winner"
        assert rows[1]["cluster"] == "small_winner"


class TestLifetimeRollupShape:

    def test_dataclass_net_property(self):
        r = LifetimeRollup(total_added=500.0, total_lost=100.0)
        assert r.net == 400.0

    def test_default_empty(self):
        r = LifetimeRollup()
        assert r.total_added == 0.0
        assert r.total_lost == 0.0
        assert r.cycle_pairs_seen == 0
        assert r.net == 0.0
