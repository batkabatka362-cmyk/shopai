"""Tests for engines._revenue_aware_captain.

Wrapper captain strategy: re-orders members_to_fire by per-
engine attribution and optionally prunes zero-revenue
members. Substrate-first -- falls back gracefully when no
attribution data is available.
"""
from __future__ import annotations

from unittest.mock import patch

from engines._clusters import get_cluster
from engines._cluster_captain import DeterministicCaptainStrategy
from engines._revenue_aware_captain import (
    RevenueAwareCaptainStrategy,
    revenue_aware_captain_enabled,
)


def _fake_engine_report(per_engine_rev: dict[str, float]):
    """Mock-friendly AttributionReport with per_engine populated."""
    from engines._revenue_attribution import (
        AttributionReport, EngineAttribution,
    )
    rpt = AttributionReport(window_hours=168.0)
    for engine, rev in per_engine_rev.items():
        rpt.per_engine.append(
            EngineAttribution(
                engine=engine, cluster=None,
                window_hours=168.0,
                attributed_revenue=rev,
                attributed_orders=1 if rev > 0 else 0,
            )
        )
    return rpt


class TestFallback:

    def test_no_attribution_data_returns_base_picks(self):
        cluster = get_cluster("retention")
        wired = ["loyalty", "churn_prediction"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({}),
        ):
            strategy = RevenueAwareCaptainStrategy()
            picks = strategy.select_members(cluster, wired, {})
        # Same set as base picks, same order (deterministic base
        # returns wired as-is)
        assert set(picks) == set(wired)

    def test_attribution_raises_falls_back(self):
        cluster = get_cluster("retention")
        wired = ["loyalty", "churn_prediction"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            side_effect=RuntimeError("net blip"),
        ):
            strategy = RevenueAwareCaptainStrategy()
            picks = strategy.select_members(cluster, wired, {})
        # Falls back to base
        assert set(picks) == set(wired)


class TestReranking:

    def test_high_revenue_engine_moves_to_front(self):
        cluster = get_cluster("retention")
        wired = ["loyalty", "churn_prediction", "subscription"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({
                "loyalty": 100.0,
                "churn_prediction": 5000.0,
                "subscription": 0.0,
            }),
        ):
            strategy = RevenueAwareCaptainStrategy()
            picks = strategy.select_members(cluster, wired, {})
        # churn_prediction (5000) ranks first
        assert picks[0] == "churn_prediction"
        # subscription (0) ranks last (below threshold)
        assert picks[-1] == "subscription"

    def test_threshold_excludes_noise(self):
        """An engine with $5 revenue (below default $10) gets
        treated as 0, so it doesn't promote past higher-zeroed
        engines."""
        cluster = get_cluster("retention")
        wired = ["a", "b", "c"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({
                "a": 5.0,    # below default $10 threshold
                "b": 1000.0, # earner
                "c": 0.0,
            }),
        ):
            strategy = RevenueAwareCaptainStrategy(
                attribution_threshold=10.0,
            )
            picks = strategy.select_members(cluster, wired, {})
        # b should rank first (1000), then a and c (both 0 after
        # threshold). Order between a and c is base-order stable.
        assert picks[0] == "b"


class TestPruning:

    def test_drop_zeros_when_others_earning(self):
        cluster = get_cluster("retention")
        wired = ["loyalty", "churn_prediction", "subscription"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({
                "loyalty": 100.0,
                "churn_prediction": 500.0,
                "subscription": 0.0,
            }),
        ):
            strategy = RevenueAwareCaptainStrategy(
                drop_zeros_when_others_earning=True,
            )
            picks = strategy.select_members(cluster, wired, {})
        # subscription dropped, only earners survive
        assert "subscription" not in picks
        assert set(picks) == {"loyalty", "churn_prediction"}

    def test_no_pruning_when_all_zero(self):
        """Safety: don't strand the cluster empty just because
        nobody earned yet."""
        cluster = get_cluster("retention")
        wired = ["loyalty", "churn_prediction"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({}),
        ):
            strategy = RevenueAwareCaptainStrategy(
                drop_zeros_when_others_earning=True,
            )
            picks = strategy.select_members(cluster, wired, {})
        # All engines preserved (data-less doesn't mean drop)
        assert set(picks) == set(wired)

    def test_pruning_off_by_default(self):
        """Default behaviour = reorder only, don't drop."""
        cluster = get_cluster("retention")
        wired = ["a", "b"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({
                "a": 100.0, "b": 0.0,
            }),
        ):
            strategy = RevenueAwareCaptainStrategy()
            picks = strategy.select_members(cluster, wired, {})
        # Both preserved (just reordered)
        assert set(picks) == {"a", "b"}


class TestCaching:

    def test_per_strategy_cache(self):
        """Two select_members calls on same instance hit
        attribute_revenue ONCE."""
        cluster = get_cluster("retention")
        wired = ["loyalty"]
        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({"loyalty": 100.0}),
        ) as mock:
            strategy = RevenueAwareCaptainStrategy()
            strategy.select_members(cluster, wired, {})
            strategy.select_members(cluster, wired, {})
            assert mock.call_count == 1


class TestEnvGate:

    def test_default_off(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_REVENUE_AWARE_CAPTAIN", raising=False,
        )
        assert revenue_aware_captain_enabled() is False

    def test_on_when_env_set(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_REVENUE_AWARE_CAPTAIN", "1",
        )
        assert revenue_aware_captain_enabled() is True


class TestPluggability:

    def test_custom_base(self):
        cluster = get_cluster("retention")
        wired = ["alpha", "beta"]

        class PickOnly:
            """Base that only picks 'alpha' regardless."""
            def select_members(self, c, w, s):
                return ["alpha"]

        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({
                "alpha": 50.0, "beta": 5000.0,
            }),
        ):
            strategy = RevenueAwareCaptainStrategy(base=PickOnly())
            picks = strategy.select_members(cluster, wired, {})
        # beta has higher revenue but wasn't in base picks --
        # wrapper doesn't introduce engines, only reorders
        assert picks == ["alpha"]


class TestEmptyBase:

    def test_empty_base_picks_returned_as_empty(self):
        cluster = get_cluster("retention")

        class EmptyBase:
            def select_members(self, c, w, s):
                return []

        with patch(
            "engines._revenue_attribution.attribute_revenue",
            return_value=_fake_engine_report({"x": 100.0}),
        ):
            strategy = RevenueAwareCaptainStrategy(base=EmptyBase())
            picks = strategy.select_members(cluster, ["x"], {})
        assert picks == []
