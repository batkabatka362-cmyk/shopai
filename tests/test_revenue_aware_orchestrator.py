"""Tests for engines._revenue_aware_orchestrator.

Wrapper strategy that re-ranks cluster_focus by attributed
revenue. Falls back to the base strategy when no attribution
data is available.
"""
from __future__ import annotations

from unittest.mock import patch

from engines._orchestrator import (
    DeterministicOrchestratorStrategy,
    StorePriority,
)
from engines._revenue_aware_orchestrator import (
    RevenueAwareOrchestratorStrategy,
    revenue_aware_enabled,
)


def _fake_report(per_cluster_rev: dict[str, float]):
    """Build an AttributionReport-shaped object with the given
    cluster -> revenue map."""
    from engines._revenue_attribution import (
        AttributionReport, ClusterAttribution,
    )
    rpt = AttributionReport(window_hours=168.0)
    for cluster, rev in per_cluster_rev.items():
        rpt.per_cluster.append(
            ClusterAttribution(
                cluster=cluster,
                window_hours=168.0,
                attributed_revenue=rev,
                attributed_orders=1 if rev > 0 else 0,
            )
        )
    return rpt


class TestFallback:

    def test_no_attribution_data_returns_base_priority(self):
        """No attribution -> wrapped strategy = base."""
        wm = {"stats": {"products": 100, "orders": 100, "total_revenue": 5000}}
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report({}),
        ):
            strategy = RevenueAwareOrchestratorStrategy()
            priority = strategy.decide_priority("store-x", wm)
        # No reranking annotation
        assert "revenue-aware rerank" not in priority.rationale

    def test_attribution_raises_falls_back(self):
        wm = {"stats": {"products": 100, "orders": 100, "total_revenue": 5000}}
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            side_effect=RuntimeError("network blip"),
        ):
            strategy = RevenueAwareOrchestratorStrategy()
            priority = strategy.decide_priority("store-x", wm)
        # Falls back -- no rerank
        assert "revenue-aware rerank" not in priority.rationale
        # Base priority's cluster_focus preserved
        deterministic = DeterministicOrchestratorStrategy().decide_priority(
            "store-x", wm,
        )
        assert priority.cluster_focus == deterministic.cluster_focus


class TestReranking:

    def test_high_revenue_cluster_moves_to_front(self):
        """Pricing made $5000, retention made $50, merchandising
        made nothing. Mature default = [retention, pricing,
        merchandising]. After rerank: [pricing, retention,
        merchandising] -- pricing forward, merchandising back."""
        wm = {"stats": {"products": 100, "orders": 100, "total_revenue": 5000}}
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report({
                "pricing": 5000.0,
                "retention": 50.0,
                "merchandising": 0.0,
            }),
        ):
            strategy = RevenueAwareOrchestratorStrategy()
            priority = strategy.decide_priority("store-x", wm)
        # pricing first (highest), retention second, merchandising last
        assert priority.cluster_focus[0] == "pricing"
        assert priority.cluster_focus[-1] == "merchandising"

    def test_threshold_excludes_noise(self):
        """A cluster with $5 revenue isn't rewarded -- noise."""
        wm = {"stats": {"products": 100, "orders": 100, "total_revenue": 5000}}
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report({
                "pricing": 5.0,  # below default $10 threshold
                "retention": 0.0,
                "merchandising": 0.0,
            }),
        ):
            strategy = RevenueAwareOrchestratorStrategy(
                attribution_threshold=10.0,
            )
            priority = strategy.decide_priority("store-x", wm)
        # No reranking happened
        deterministic = DeterministicOrchestratorStrategy().decide_priority(
            "store-x", wm,
        )
        assert priority.cluster_focus == deterministic.cluster_focus

    def test_priority_bucket_unchanged(self):
        """Revenue rerank shouldn't change the priority CLASS
        (mature/at_risk/etc) -- just reorders within."""
        wm_mature = {
            "stats": {"products": 100, "orders": 100, "total_revenue": 5000},
        }
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report({
                "pricing": 10000.0, "retention": 5000.0,
            }),
        ):
            strategy = RevenueAwareOrchestratorStrategy()
            priority = strategy.decide_priority("store-x", wm_mature)
        assert priority.priority == "mature"

    def test_annotation_added_to_rationale(self):
        wm = {"stats": {"products": 100, "orders": 100, "total_revenue": 5000}}
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report({
                "pricing": 1234.0,
            }),
        ):
            strategy = RevenueAwareOrchestratorStrategy()
            priority = strategy.decide_priority("store-x", wm)
        assert "revenue-aware rerank" in priority.rationale
        assert "pricing=$1234" in priority.rationale

    def test_signals_carry_revenue_marker(self):
        wm = {"stats": {"products": 100, "orders": 100, "total_revenue": 5000}}
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report({
                "pricing": 1000.0,
            }),
        ):
            strategy = RevenueAwareOrchestratorStrategy()
            priority = strategy.decide_priority("store-x", wm)
        assert priority.signals.get("revenue_aware") is True
        assert "pricing" in priority.signals.get("ranked_clusters", [])


class TestCaching:

    def test_per_store_attribution_cached(self):
        """Two calls for the same store hit attribute_revenue
        only once -- the wrapper caches per store."""
        wm = {"stats": {"products": 100, "orders": 100, "total_revenue": 5000}}
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report({}),
        ) as mock:
            strategy = RevenueAwareOrchestratorStrategy()
            strategy.decide_priority("store-x", wm)
            strategy.decide_priority("store-x", wm)
            assert mock.call_count == 1


class TestEnvGate:

    def test_default_off(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_REVENUE_AWARE_ORCHESTRATOR", raising=False,
        )
        assert revenue_aware_enabled() is False

    def test_on_when_env_set(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_REVENUE_AWARE_ORCHESTRATOR", "1",
        )
        assert revenue_aware_enabled() is True


class TestPluggability:

    def test_custom_base_strategy(self):
        """Wrapper can wrap any OrchestratorStrategy, not just
        the deterministic default."""

        class FakeBase:
            def decide_priority(self, store_id, world_model):
                return StorePriority(
                    store_id=store_id,
                    priority="custom",
                    cluster_focus=["retention", "pricing"],
                    rationale="fake base says custom",
                )

        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_report({
                "pricing": 1000.0, "retention": 100.0,
            }),
        ):
            strategy = RevenueAwareOrchestratorStrategy(
                base=FakeBase(),
            )
            priority = strategy.decide_priority("store-x", {})
        # Base bucket preserved
        assert priority.priority == "custom"
        # But reranked -- pricing first
        assert priority.cluster_focus[0] == "pricing"
