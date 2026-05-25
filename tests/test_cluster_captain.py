"""Tests for engines._cluster_captain."""
from __future__ import annotations

from unittest.mock import patch

from engines._cluster_captain import (
    CaptainPlan,
    DeterministicCaptainStrategy,
    SignalDrivenCaptainStrategy,
    MemoryAwareCaptainStrategy,
    make_captain_plan,
    cluster_health,
)
from engines._cluster_memory import ClusterHealth


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


class TestSignalDrivenStrategy:
    """Per-cluster rules: signals -> selected members."""

    def test_retention_at_risk_signal_fires_churn(self):
        plan = make_captain_plan(
            "retention",
            signals={"at_risk_count": 5},
            strategy=SignalDrivenCaptainStrategy(),
        )
        fired = {m["engine"] for m in plan.members_to_fire}
        # at_risk > 0 -> churn-focused members fire
        assert "churn_prediction" in fired
        assert "cohort_analysis" in fired
        # always-on members
        assert "loyalty" in fired

    def test_retention_no_signals_fires_only_default(self):
        # Empty signals -> only the "always-on" default rule fires
        plan = make_captain_plan(
            "retention",
            signals={},
            strategy=SignalDrivenCaptainStrategy(),
        )
        fired = {m["engine"] for m in plan.members_to_fire}
        # Default-rule members
        assert "loyalty" in fired
        assert "customer_effort_score" in fired
        # Signal-gated members should NOT fire without signal
        assert "churn_prediction" not in fired
        assert "cart_recovery" not in fired

    def test_retention_cart_signal_fires_recovery(self):
        plan = make_captain_plan(
            "retention",
            signals={"abandoned_cart_count": 3},
            strategy=SignalDrivenCaptainStrategy(),
        )
        fired = {m["engine"] for m in plan.members_to_fire}
        assert "cart_recovery" in fired
        assert "browse_recovery" in fired
        # No at_risk signal -> churn doesn't fire
        assert "churn_prediction" not in fired

    def test_pricing_thin_margin_signal(self):
        plan = make_captain_plan(
            "pricing",
            signals={"thin_margin_count": 5},
            strategy=SignalDrivenCaptainStrategy(),
        )
        fired = {m["engine"] for m in plan.members_to_fire}
        assert "dropshipping" in fired
        assert "profitability_calculator" in fired
        # default always-on
        assert "price_elasticity" in fired

    def test_quality_negative_review_threshold(self):
        # Threshold is >=3, so 2 negative reviews shouldn't fire
        plan = make_captain_plan(
            "quality",
            signals={"negative_review_count": 2},
            strategy=SignalDrivenCaptainStrategy(),
        )
        fired = {m["engine"] for m in plan.members_to_fire}
        assert "review_management" not in fired

        # 3 negative reviews DOES fire
        plan = make_captain_plan(
            "quality",
            signals={"negative_review_count": 3},
            strategy=SignalDrivenCaptainStrategy(),
        )
        fired = {m["engine"] for m in plan.members_to_fire}
        assert "review_management" in fired

    def test_uncurated_cluster_falls_back_to_fire_all(self):
        # 'governance' cluster has no rules in _CLUSTER_RULES
        # -- should fall back to firing all wired members
        plan = make_captain_plan(
            "governance",
            signals={},
            strategy=SignalDrivenCaptainStrategy(),
        )
        # All wired governance members should fire (could be
        # 0 if none wired, but the strategy should at least
        # not RAISE)
        assert plan.cluster == "governance"

    def test_signals_with_strings_dont_crash(self):
        # Bad signal types should be silently ignored
        plan = make_captain_plan(
            "retention",
            signals={"at_risk_count": "not a number"},
            strategy=SignalDrivenCaptainStrategy(),
        )
        # at_risk_count signal can't compare -> only defaults fire
        fired = {m["engine"] for m in plan.members_to_fire}
        assert "loyalty" in fired
        assert "churn_prediction" not in fired


class TestMemoryAwareStrategy:
    """Captain reads cluster health, adjusts selection."""

    def _mock_health(self, verdict, member_health=None):
        # Stat ratios target each verdict band:
        #   healthy   >= 80% success rate
        #   warning   50-80%
        #   unhealthy < 50%
        if verdict == "healthy":
            exec_, failed = 90, 5
        elif verdict == "warning":
            exec_, failed = 70, 20
        else:  # unhealthy
            exec_, failed = 10, 60
        return ClusterHealth(
            cluster="retention",
            member_count=9,
            wired_count=9,
            total_executed=exec_,
            total_failed=failed,
            total_rejected=5,
            member_health=member_health or [],
        )

    def test_healthy_cluster_uses_signal_driven_as_is(self):
        with patch(
            "engines._cluster_memory.cluster_health_rollup",
            return_value=self._mock_health("healthy"),
        ):
            plan = make_captain_plan(
                "retention",
                signals={"at_risk_count": 5},
                strategy=MemoryAwareCaptainStrategy(),
            )
        fired = {m["engine"] for m in plan.members_to_fire}
        # Same as signal-driven would pick
        assert "churn_prediction" in fired
        assert "loyalty" in fired

    def test_warning_cluster_drops_failing_members(self):
        # loyalty has bad history -- should be dropped
        member_health = [
            {
                "engine": "loyalty",
                "wired": True,
                "executed": 2,
                "failed": 8,
                "rejected": 0,
                "pending": 0,
                "positive": 1,
                "negative": 7,
                "revenue": 0.0,
            },
            {
                "engine": "churn_prediction",
                "wired": True,
                "executed": 10,
                "failed": 1,
                "rejected": 0,
                "pending": 0,
                "positive": 8,
                "negative": 1,
                "revenue": 0.0,
            },
        ]
        with patch(
            "engines._cluster_memory.cluster_health_rollup",
            return_value=self._mock_health(
                "warning", member_health,
            ),
        ):
            plan = make_captain_plan(
                "retention",
                signals={"at_risk_count": 5},
                strategy=MemoryAwareCaptainStrategy(),
            )
        fired = {m["engine"] for m in plan.members_to_fire}
        # Loyalty had failed > executed -> dropped
        assert "loyalty" not in fired
        # churn_prediction has good history -> kept
        assert "churn_prediction" in fired

    def test_unhealthy_cluster_collapses_to_defaults(self):
        with patch(
            "engines._cluster_memory.cluster_health_rollup",
            return_value=self._mock_health("unhealthy"),
        ):
            plan = make_captain_plan(
                "retention",
                signals={"at_risk_count": 5},
                strategy=MemoryAwareCaptainStrategy(),
            )
        fired = {m["engine"] for m in plan.members_to_fire}
        # retention defaults: loyalty + customer_effort_score
        # Cluster unhealthy -> only those default-rule
        # members fire (even though at_risk signal matched)
        assert "churn_prediction" not in fired
        assert "loyalty" in fired
        assert "customer_effort_score" in fired

    def test_unknown_verdict_uses_signal_driven(self):
        # No actions yet -> verdict is unknown -> use base
        with patch(
            "engines._cluster_memory.cluster_health_rollup",
            return_value=None,
        ):
            plan = make_captain_plan(
                "retention",
                signals={"at_risk_count": 5},
                strategy=MemoryAwareCaptainStrategy(),
            )
        fired = {m["engine"] for m in plan.members_to_fire}
        assert "churn_prediction" in fired

    def test_regression_signal_escalates_healthy_to_warning(self):
        """Wave 13: when bus carries recent_regression_count >=
        1 for this cluster, healthy verdict is treated as
        warning -- captain prunes failing members."""
        # healthy verdict + bad member history. Without
        # regression: healthy = keep all. With regression =
        # warning = drop failing members.
        member_health = [
            {
                "engine": "loyalty",
                "wired": True,
                "executed": 2,
                "failed": 8,
                "rejected": 0,
                "pending": 0,
                "positive": 0,
                "negative": 0,
                "revenue": 0.0,
            },
        ]
        with patch(
            "engines._cluster_memory.cluster_health_rollup",
            return_value=self._mock_health(
                "healthy", member_health,
            ),
        ):
            plan = make_captain_plan(
                "retention",
                signals={
                    "at_risk_count": 5,
                    "recent_regression_count": 2,
                },
                strategy=MemoryAwareCaptainStrategy(),
            )
        fired = {m["engine"] for m in plan.members_to_fire}
        # With regression signal -> healthy-bumped-to-warning
        # -> loyalty (bad history) is dropped
        assert "loyalty" not in fired

    def test_declining_revenue_verdict_escalates(self):
        """Wave 18: ClusterHealth.revenue_verdict == declining
        escalates verdict by one tier even without a bus signal."""
        member_health = [
            {
                "engine": "loyalty",
                "wired": True,
                "executed": 2,
                "failed": 8,
                "rejected": 0,
                "pending": 0,
                "positive": 0,
                "negative": 0,
                "revenue": 0.0,
            },
        ]
        health = self._mock_health("healthy", member_health)
        health._force_declining = True
        with patch(
            "engines._cluster_memory.cluster_health_rollup",
            return_value=health,
        ):
            plan = make_captain_plan(
                "retention",
                signals={"at_risk_count": 5},
                strategy=MemoryAwareCaptainStrategy(),
            )
        fired = {m["engine"] for m in plan.members_to_fire}
        # healthy + declining -> warning tier -> drops loyalty
        # (bad history)
        assert "loyalty" not in fired

    def test_regression_signal_takes_precedence_over_declining(self):
        """Both signals active should not double-escalate."""
        member_health = [
            {
                "engine": "loyalty",
                "wired": True,
                "executed": 2,
                "failed": 8,
                "rejected": 0,
                "pending": 0,
                "positive": 0,
                "negative": 0,
                "revenue": 0.0,
            },
        ]
        health = self._mock_health("healthy", member_health)
        health._force_declining = True
        with patch(
            "engines._cluster_memory.cluster_health_rollup",
            return_value=health,
        ):
            plan = make_captain_plan(
                "retention",
                signals={
                    "at_risk_count": 5,
                    "recent_regression_count": 1,
                },
                strategy=MemoryAwareCaptainStrategy(),
            )
        fired = {m["engine"] for m in plan.members_to_fire}
        # Single escalation (regression signal path) -- loyalty
        # dropped via warning tier, NOT collapsed to defaults
        # (which would be unhealthy = two escalations)
        assert "loyalty" not in fired
        # churn_prediction has good history -> survives warning
        assert "churn_prediction" in fired

    def test_regression_signal_escalates_warning_to_unhealthy(self):
        """Warning + regression -> unhealthy = collapse to
        defaults."""
        member_health = [
            {
                "engine": "churn_prediction",
                "wired": True,
                "executed": 10,
                "failed": 1,
                "rejected": 0,
                "pending": 0,
                "positive": 0,
                "negative": 0,
                "revenue": 0.0,
            },
        ]
        with patch(
            "engines._cluster_memory.cluster_health_rollup",
            return_value=self._mock_health(
                "warning", member_health,
            ),
        ):
            plan = make_captain_plan(
                "retention",
                signals={
                    "at_risk_count": 5,
                    "recent_regression_count": 1,
                },
                strategy=MemoryAwareCaptainStrategy(),
            )
        fired = {m["engine"] for m in plan.members_to_fire}
        # Warning + regression -> unhealthy -> only defaults
        # fire (loyalty + customer_effort_score)
        assert "churn_prediction" not in fired
        assert "loyalty" in fired
