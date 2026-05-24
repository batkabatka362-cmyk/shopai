"""Tests for engines._cluster_memory."""
from __future__ import annotations

from engines._cluster_memory import (
    ClusterHealth,
    QueueOutcomeRollup,
    cluster_health_rollup,
    fleet_cluster_health,
)
from engines._clusters import get_cluster


class TestHealthVerdict:

    def test_healthy_above_80pct(self):
        h = ClusterHealth(
            cluster="x", member_count=5, wired_count=5,
            total_executed=80, total_failed=10, total_rejected=10,
        )
        assert h.success_rate == 0.8
        assert h.health_verdict == "healthy"

    def test_warning_between_50_and_80(self):
        h = ClusterHealth(
            cluster="x", member_count=5, wired_count=5,
            total_executed=60, total_failed=30, total_rejected=10,
        )
        assert h.health_verdict == "warning"

    def test_unhealthy_below_50(self):
        h = ClusterHealth(
            cluster="x", member_count=5, wired_count=5,
            total_executed=10, total_failed=50, total_rejected=40,
        )
        assert h.health_verdict == "unhealthy"

    def test_unknown_with_no_actions(self):
        h = ClusterHealth(
            cluster="x", member_count=5, wired_count=5,
        )
        assert h.health_verdict == "unknown"


class TestPositiveRatio:

    def test_positive_ratio(self):
        h = ClusterHealth(
            cluster="x", member_count=5, wired_count=5,
            positive_outcomes=7,
            negative_outcomes=2,
            neutral_outcomes=1,
        )
        assert h.positive_ratio == 0.7

    def test_zero_outcomes(self):
        h = ClusterHealth(
            cluster="x", member_count=5, wired_count=5,
        )
        assert h.positive_ratio == 0.0


class TestQueueRollup:
    """Run against the real codebase. Most clusters will
    have zero activity in CI but the structure should
    materialize correctly."""

    def test_retention_cluster_health_shape(self):
        cluster = get_cluster("retention")
        assert cluster is not None
        rollup = QueueOutcomeRollup()
        health = rollup.health_for(cluster)
        assert health.cluster == "retention"
        assert health.member_count > 0
        assert health.wired_count > 0
        # Member health rows -- one per member
        assert len(health.member_health) == health.member_count
        for row in health.member_health:
            assert "engine" in row
            assert "wired" in row

    def test_unknown_cluster_returns_none(self):
        assert cluster_health_rollup("does-not-exist") is None


class TestFleetHealth:

    def test_fleet_health_returns_all_clusters(self):
        all_health = fleet_cluster_health()
        # 10 clusters expected
        assert len(all_health) == 10
        names = {h.cluster for h in all_health}
        assert "retention" in names
        assert "pricing" in names


class TestStrategyPluggable:

    def test_custom_strategy(self):
        class FakeStrategy:
            def health_for(self, cluster):
                return ClusterHealth(
                    cluster=cluster.name,
                    member_count=len(cluster.members),
                    wired_count=0,
                    total_executed=999,
                )

        rollup = cluster_health_rollup(
            "retention", strategy=FakeStrategy(),
        )
        assert rollup is not None
        assert rollup.total_executed == 999
