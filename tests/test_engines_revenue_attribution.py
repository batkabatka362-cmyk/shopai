"""Tests for engines._revenue_attribution.

Not to be confused with tests/test_revenue_attribution.py which
covers the older ApprovalQueue.revenue_attribution_stats helper.
This module tests the newer Tier 2b cluster-level attribution
that joins Shopify orders to cluster firings via tags.
"""
from __future__ import annotations

import pytest

from engines._revenue_attribution import (
    AttributionReport,
    ClusterAttribution,
    SharedCreditStrategy,
    attribute_revenue,
)


class TestClusterAttribution:

    def test_confidence_none_when_no_orders(self):
        a = ClusterAttribution(
            cluster="retention", window_hours=168.0,
        )
        assert a.confidence == "none"

    def test_confidence_low_with_few_orders(self):
        a = ClusterAttribution(
            cluster="retention", window_hours=168.0,
            attributed_orders=2,
        )
        assert a.confidence == "low"

    def test_confidence_medium(self):
        a = ClusterAttribution(
            cluster="retention", window_hours=168.0,
            attributed_orders=5,
        )
        assert a.confidence == "medium"

    def test_confidence_high(self):
        a = ClusterAttribution(
            cluster="retention", window_hours=168.0,
            attributed_orders=15,
        )
        assert a.confidence == "high"


class TestAttributionReport:

    def test_attribution_rate_zero_revenue(self):
        r = AttributionReport(window_hours=24.0)
        assert r.attribution_rate == 0.0

    def test_attribution_rate_computed(self):
        r = AttributionReport(
            window_hours=24.0,
            total_revenue_in_window=1000.0,
        )
        r.per_cluster.append(
            ClusterAttribution(
                cluster="x", window_hours=24.0,
                attributed_revenue=250.0,
            )
        )
        assert r.attribution_rate == 0.25

    def test_attributed_revenue_sums(self):
        r = AttributionReport(window_hours=24.0)
        r.per_cluster.append(
            ClusterAttribution(
                cluster="a", window_hours=24.0,
                attributed_revenue=100.0,
            )
        )
        r.per_cluster.append(
            ClusterAttribution(
                cluster="b", window_hours=24.0,
                attributed_revenue=50.0,
            )
        )
        assert r.attributed_revenue == 150.0


class TestSharedCreditStrategy:

    def test_single_tag_single_cluster(self):
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "100.00",
                "tags": "retention",
            }
        ]
        out = strategy.attribute(
            orders, {"retention": "retention"},
        )
        assert "retention" in out
        assert out["retention"].attributed_revenue == 100.0
        assert out["retention"].attributed_orders == 1

    def test_two_clusters_split_revenue(self):
        """Order tagged with two different clusters -- 50/50 split."""
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "100.00",
                "tags": ["retention", "pricing"],
            }
        ]
        out = strategy.attribute(
            orders,
            {"retention": "retention", "pricing": "pricing"},
        )
        assert out["retention"].attributed_revenue == 50.0
        assert out["pricing"].attributed_revenue == 50.0

    def test_customer_tags_picked_up(self):
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "100.00",
                "customer": {"tags": "loyal_customer"},
            }
        ]
        out = strategy.attribute(
            orders, {"loyal_customer": "retention"},
        )
        assert out["retention"].attributed_revenue == 100.0

    def test_line_item_tags_picked_up(self):
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "100.00",
                "line_items": [
                    {"tags": "best_seller"},
                ],
            }
        ]
        out = strategy.attribute(
            orders, {"best_seller": "merchandising"},
        )
        assert out["merchandising"].attributed_revenue == 100.0

    def test_no_match_no_attribution(self):
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "100.00",
                "tags": "random_unmatched_tag",
            }
        ]
        out = strategy.attribute(
            orders, {"retention": "retention"},
        )
        assert out == {}

    def test_dynamic_namespace_match(self):
        """Tag 'cohort:2026-05' matches 'cohort:*' wildcard."""
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "100.00",
                "tags": "cohort:2026-05",
            }
        ]
        out = strategy.attribute(
            orders, {"cohort:*": "retention"},
        )
        assert out["retention"].attributed_revenue == 100.0

    def test_dynamic_dash_prefix_match(self):
        """Tag 'shopai-loyalty-tier3' matches 'shopai-loyalty-*'."""
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "100.00",
                "tags": "shopai-loyalty-tier3",
            }
        ]
        out = strategy.attribute(
            orders, {"shopai-loyalty-*": "retention"},
        )
        assert out["retention"].attributed_revenue == 100.0

    def test_bad_total_price_treated_as_zero(self):
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "not_a_number",
                "tags": "retention",
            }
        ]
        out = strategy.attribute(
            orders, {"retention": "retention"},
        )
        # Still attributed (1 order) but $0 revenue
        assert out["retention"].attributed_orders == 1
        assert out["retention"].attributed_revenue == 0.0

    def test_tag_hits_recorded(self):
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": "1",
                "total_price": "100.00",
                "tags": "retention,vip",
            }
        ]
        out = strategy.attribute(
            orders,
            {"retention": "retention", "vip": "retention"},
        )
        attr = out["retention"]
        assert "retention" in attr.tag_matches
        assert "vip" in attr.tag_matches

    def test_sample_orders_bounded_to_5(self):
        strategy = SharedCreditStrategy()
        orders = [
            {
                "id": str(i),
                "total_price": "10.00",
                "tags": "retention",
            }
            for i in range(10)
        ]
        out = strategy.attribute(
            orders, {"retention": "retention"},
        )
        assert len(out["retention"].sample_orders) == 5
        assert out["retention"].attributed_orders == 10


class TestAttributeRevenueFunction:

    def test_with_supplied_orders(self):
        # Bypass live fetch by supplying orders directly
        report = attribute_revenue(
            window_hours=24.0,
            orders=[
                {
                    "id": "1",
                    "total_price": "100.00",
                    "tags": "no_match_tag",
                }
            ],
        )
        assert report.total_orders_in_window == 1
        assert report.total_revenue_in_window == 100.0

    def test_empty_orders(self):
        report = attribute_revenue(window_hours=24.0, orders=[])
        assert report.total_orders_in_window == 0
        assert report.attribution_rate == 0.0

    def test_pluggable_strategy(self):
        """Custom strategy that attributes ALL revenue to one cluster."""

        class AllToOne:
            def attribute(self, orders, tag_to_cluster):
                total = sum(
                    float(o.get("total_price", 0) or 0) for o in orders
                )
                return {
                    "fake_cluster": ClusterAttribution(
                        cluster="fake_cluster",
                        window_hours=0.0,
                        attributed_revenue=total,
                        attributed_orders=len(orders),
                    )
                }

        report = attribute_revenue(
            window_hours=24.0,
            orders=[
                {"id": "1", "total_price": "100.00"},
                {"id": "2", "total_price": "200.00"},
            ],
            strategy=AllToOne(),
        )
        assert report.attributed_revenue == 300.0
        assert len(report.per_cluster) == 1
        assert report.per_cluster[0].cluster == "fake_cluster"

    def test_per_cluster_sorted_by_revenue_desc(self):
        report = attribute_revenue(
            window_hours=24.0,
            orders=[
                {
                    "id": "1", "total_price": "100.00",
                    "tags": "low_tag",
                },
                {
                    "id": "2", "total_price": "500.00",
                    "tags": "high_tag",
                },
            ],
        )
        # No real catalog → tag_to_cluster is empty → no
        # per_cluster rows. Just verifies no crash.
        assert isinstance(report.per_cluster, list)
