"""Tests for engines._cluster_memory."""
from __future__ import annotations

from engines._cluster_memory import (
    ClusterHealth,
    QueueOutcomeRollup,
    cluster_health_rollup,
    enrich_with_attribution,
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


class TestRevenueVerdict:
    """Wave 18: revenue_verdict is a separate signal from
    health_verdict so callers can reason about ROI vs uptime."""

    def test_unknown_when_no_attribution_orders(self):
        h = ClusterHealth(
            cluster="x", member_count=1, wired_count=1,
        )
        assert h.revenue_verdict == "unknown"

    def test_earning_when_above_threshold(self):
        h = ClusterHealth(
            cluster="x", member_count=1, wired_count=1,
            attributed_revenue=500.0,
            attribution_orders=5,
        )
        assert h.revenue_verdict == "earning"

    def test_flat_when_orders_but_low_revenue(self):
        h = ClusterHealth(
            cluster="x", member_count=1, wired_count=1,
            attributed_revenue=5.0,
            attribution_orders=2,
        )
        assert h.revenue_verdict == "flat"

    def test_declining_when_force_flag_set(self):
        """enrich_with_attribution sets _force_declining when
        the latest delta carries an alert against this cluster."""
        h = ClusterHealth(
            cluster="x", member_count=1, wired_count=1,
            attributed_revenue=500.0,
            attribution_orders=5,
        )
        h._force_declining = True
        assert h.revenue_verdict == "declining"

    def test_independent_from_health_verdict(self):
        """A cluster can be operationally healthy (success_rate
        high) but bring zero revenue."""
        h = ClusterHealth(
            cluster="x", member_count=1, wired_count=1,
            total_executed=100, total_failed=5,  # healthy
            attribution_orders=0,  # but unknown revenue
        )
        assert h.health_verdict == "healthy"
        assert h.revenue_verdict == "unknown"


class TestAttributionEnrichment:
    """enrich_with_attribution mutates ClusterHealth with
    Shopify-order-derived revenue. Stays additive -- existing
    total_revenue (self-reported) is unchanged."""

    def test_no_orders_leaves_attribution_zero(self):
        healths = [
            ClusterHealth(
                cluster="retention",
                member_count=5, wired_count=3,
                total_revenue=100.0,
            )
        ]
        enrich_with_attribution(healths, orders=[])
        h = healths[0]
        assert h.attributed_revenue == 0.0
        assert h.attribution_orders == 0
        assert h.attribution_confidence == "none"
        # total_revenue (self-reported) untouched
        assert h.total_revenue == 100.0

    def test_window_hours_recorded_even_when_no_match(self):
        """Window is recorded so dashboards know what scope
        the zero represents."""
        healths = [
            ClusterHealth(
                cluster="retention",
                member_count=1, wired_count=1,
            )
        ]
        enrich_with_attribution(
            healths, orders=[], window_hours=72.0,
        )
        assert healths[0].attribution_window_hours == 72.0

    def test_returns_list_for_chaining(self):
        healths = [
            ClusterHealth(
                cluster="x", member_count=1, wired_count=0,
            )
        ]
        out = enrich_with_attribution(healths, orders=[])
        assert out is healths

    def test_empty_list_is_noop(self):
        out = enrich_with_attribution([], orders=[])
        assert out == []

    def test_alert_flips_cluster_to_declining(self):
        """Wave 18: when latest delta has an alert against a
        cluster, enrich flips its revenue_verdict to declining."""
        from unittest.mock import patch
        from engines._attribution_delta import (
            AttributionDelta, RegressionAlert,
        )
        fake_delta = AttributionDelta(
            prior_snapshot_id="a", latest_snapshot_id="b",
            prior_captured_at=1.0, latest_captured_at=2.0,
            prior_total_revenue=1000.0,
            latest_total_revenue=500.0,
            prior_attributed_revenue=800.0,
            latest_attributed_revenue=200.0,
            alerts=[
                RegressionAlert(
                    scope="cluster", name="retention",
                    prior_revenue=800.0, latest_revenue=200.0,
                    delta_pct=-0.75,
                    reason="revenue dropped 75%",
                ),
            ],
        )
        healths = [
            ClusterHealth(
                cluster="retention",
                member_count=5, wired_count=3,
                attributed_revenue=200.0,
                attribution_orders=3,
            ),
            ClusterHealth(
                cluster="pricing",
                member_count=5, wired_count=3,
                attributed_revenue=300.0,
                attribution_orders=4,
            ),
        ]
        with patch(
            "engines._attribution_delta.latest_delta",
            return_value=fake_delta,
        ):
            enrich_with_attribution(healths, orders=[])
        retention = next(h for h in healths if h.cluster == "retention")
        pricing = next(h for h in healths if h.cluster == "pricing")
        assert retention.revenue_verdict == "declining"
        # pricing not flagged in delta -> still earning
        assert pricing.revenue_verdict == "earning"


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
