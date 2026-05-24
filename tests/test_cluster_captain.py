"""Tests for engines._cluster_captain."""
from __future__ import annotations

from engines._cluster_captain import (
    CaptainPlan,
    DeterministicCaptainStrategy,
    make_captain_plan,
    cluster_health,
)


class TestUnknownCluster:

    def test_unknown_cluster_returns_empty_plan(self):
        plan = make_captain_plan("does-not-exist")
        assert plan.fire_count == 0
        assert plan.cluster == "does-not-exist"
        assert any("unknown cluster" in n for n in plan.notes)


class TestRetentionCluster:
    """Retention cluster: all wired members are additive
    (tag-only writebacks). Captain should fire all of them
    automatically."""

    def test_retention_all_auto_fire(self):
        plan = make_captain_plan("retention", store_id="store-A")
        assert plan.fire_count >= 5, (
            f"Expected retention to have multiple wired "
            f"members, got {plan.fire_count}"
        )
        assert plan.auto_count == plan.fire_count, (
            "All retention members should be additive -> auto"
        )
        assert not plan.modifications_queued, (
            "Retention has no modification-tier engines"
        )

    def test_retention_members_have_apply_flags(self):
        plan = make_captain_plan("retention")
        for m in plan.members_to_fire:
            assert m["apply_flag"], (
                f"Retention member {m['engine']} should have "
                f"an apply_flag set"
            )
            assert m["apply_flag"].startswith("apply_")

    def test_retention_includes_known_engines(self):
        plan = make_captain_plan("retention")
        engines_firing = {m["engine"] for m in plan.members_to_fire}
        # These are all wired retention engines
        expected_some = {"loyalty", "churn_prediction"}
        assert expected_some.issubset(engines_firing), (
            f"Missing expected retention engines. "
            f"Got: {engines_firing}"
        )


class TestPricingCluster:
    """Pricing cluster: mix of additive (tag) and modification
    (actual price changes). Captain MUST split correctly."""

    def test_pricing_modifications_are_queued(self):
        plan = make_captain_plan("pricing", store_id="store-A")
        queued_engines = {
            m["engine"] for m in plan.modifications_queued
        }
        # dynamic_pricing + pricing both change actual prices
        assert "dynamic_pricing" in queued_engines, (
            "dynamic_pricing must be enqueued -- price changes "
            "are modification-tier and require approval"
        )

    def test_pricing_additive_members_auto_fire(self):
        plan = make_captain_plan("pricing", store_id="store-A")
        fire_engines = {m["engine"] for m in plan.members_to_fire}
        # These write tags only -- additive
        assert "price_elasticity" in fire_engines

    def test_no_overlap_fire_and_queued(self):
        plan = make_captain_plan("pricing")
        fire = {m["engine"] for m in plan.members_to_fire}
        queued = {m["engine"] for m in plan.modifications_queued}
        assert not (fire & queued), (
            "Engine cannot be both auto-fired AND queued"
        )


class TestRiskTierEnforcement:

    def test_every_fired_engine_is_additive(self):
        """Architectural invariant: captain auto-fires ONLY
        additive-tier engines. Modification + destructive
        always need higher-tier approval."""
        for cluster_name in [
            "pricing", "retention", "acquisition",
            "quality", "merchandising", "fulfillment",
        ]:
            plan = make_captain_plan(cluster_name)
            for m in plan.members_to_fire:
                assert m["risk"] == "additive", (
                    f"Cluster {cluster_name}: engine "
                    f"{m['engine']} fired with risk={m['risk']} "
                    f"-- only additive may auto-fire"
                )


class TestClusterHealth:

    def test_health_shape(self):
        h = cluster_health("retention")
        assert h["cluster"] == "retention"
        assert "kpi" in h
        assert "total_members" in h
        assert "wired_members" in h
        assert "risk_buckets" in h
        assert "members" in h

    def test_health_unknown_cluster(self):
        h = cluster_health("does-not-exist")
        assert "error" in h

    def test_health_member_rows_have_risk(self):
        h = cluster_health("pricing")
        for row in h["members"]:
            assert "engine" in row
            assert "writeback" in row
            assert "risk" in row


class TestStrategyPluggable:

    def test_strategy_can_exclude_members(self):
        """Custom strategies can pre-filter which members
        the captain considers."""

        class OnlyLoyaltyStrategy:
            def select_members(self, cluster, wired_members, signals):
                return [m for m in wired_members if m == "loyalty"]

        plan = make_captain_plan(
            "retention",
            strategy=OnlyLoyaltyStrategy(),
        )
        fire_engines = {m["engine"] for m in plan.members_to_fire}
        assert fire_engines == {"loyalty"}, (
            f"Custom strategy should fire only loyalty, "
            f"got {fire_engines}"
        )

    def test_deterministic_strategy_fires_all_wired(self):
        # DeterministicCaptainStrategy is the default
        plan = make_captain_plan(
            "retention",
            strategy=DeterministicCaptainStrategy(),
        )
        # Should match default behavior
        plan_default = make_captain_plan("retention")
        assert plan.fire_count == plan_default.fire_count


class TestSignalsPassthrough:

    def test_signals_dict_passed_to_strategy(self):
        received = {}

        class CapturingStrategy:
            def select_members(self, cluster, wired_members, signals):
                received["signals"] = signals
                received["wired_count"] = len(wired_members)
                return list(wired_members)

        make_captain_plan(
            "retention",
            signals={"at_risk_count": 42, "trend": "up"},
            strategy=CapturingStrategy(),
        )
        assert received["signals"]["at_risk_count"] == 42
        assert received["signals"]["trend"] == "up"
        assert received["wired_count"] > 0
