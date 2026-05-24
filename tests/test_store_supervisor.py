"""Tests for engines._store_supervisor."""
from __future__ import annotations

from engines._store_supervisor import (
    SupervisorPlan,
    make_supervisor_plan,
    supervisor_summary,
)


class TestDefaultActivation:
    """Default: every cluster active except opt-in ones."""

    def test_default_skips_setup_and_content(self):
        plan = make_supervisor_plan(store_id="store-A")
        skipped_names = {
            s["cluster"] for s in plan.skipped_clusters
        }
        assert "setup" in skipped_names
        assert "content" in skipped_names

    def test_default_activates_eight_clusters(self):
        plan = make_supervisor_plan(store_id="store-A")
        # 10 total - 2 opt-in = 8
        assert len(plan.active_clusters) == 8

    def test_default_includes_core_clusters(self):
        plan = make_supervisor_plan(store_id="store-A")
        active = set(plan.active_clusters)
        for core in [
            "retention", "pricing", "acquisition",
            "quality", "merchandising", "fulfillment",
        ]:
            assert core in active, (
                f"Core cluster '{core}' should activate "
                f"by default"
            )

    def test_skipped_reasons_present(self):
        plan = make_supervisor_plan()
        for s in plan.skipped_clusters:
            assert s["reason"] == "opt_in_only", (
                f"Default-skipped cluster {s['cluster']} "
                f"should have opt_in_only reason"
            )


class TestPriorityOverride:
    """cluster_override pins activation to a subset."""

    def test_override_activates_only_named(self):
        plan = make_supervisor_plan(
            store_id="store-A",
            cluster_override=["retention", "quality"],
        )
        assert set(plan.active_clusters) == {"retention", "quality"}

    def test_override_skips_rest_with_reason(self):
        plan = make_supervisor_plan(
            cluster_override=["retention"],
        )
        for s in plan.skipped_clusters:
            assert s["reason"] == "not_in_priority_override"

    def test_empty_override_skips_everything(self):
        plan = make_supervisor_plan(cluster_override=[])
        assert plan.active_clusters == []

    def test_override_for_opt_in_cluster_still_activates(self):
        # cluster_override is more authoritative than opt-in
        # gating -- operator can explicitly fire `setup`
        plan = make_supervisor_plan(
            cluster_override=["setup"],
        )
        assert "setup" in plan.active_clusters


class TestSignalsPropagation:
    """Per-cluster signals reach the right captain."""

    def test_signals_select_specific_members(self):
        # at_risk_count=5 in retention -> only churn-focused
        # members + defaults fire (no cart_recovery without
        # abandoned_cart signal)
        plan = make_supervisor_plan(
            cluster_override=["retention"],
            signals_by_cluster={
                "retention": {"at_risk_count": 5},
            },
        )
        retention_plan = next(
            p for p in plan.captain_plans
            if p.cluster == "retention"
        )
        fired = {m["engine"] for m in retention_plan.members_to_fire}
        assert "churn_prediction" in fired
        assert "cart_recovery" not in fired

    def test_no_signals_falls_back_to_fire_all(self):
        plan = make_supervisor_plan(
            cluster_override=["retention"],
        )
        retention_plan = next(
            p for p in plan.captain_plans
            if p.cluster == "retention"
        )
        # No signals -> deterministic strategy -> all 9 wired
        # members fire (retention has 9 wired)
        assert retention_plan.fire_count == 9


class TestSummary:

    def test_summary_shape(self):
        plan = make_supervisor_plan(store_id="store-A")
        s = supervisor_summary(plan)
        assert "store_id" in s
        assert "active_clusters" in s
        assert "total_to_fire" in s
        assert "cluster_breakdown" in s
        assert isinstance(s["cluster_breakdown"], list)

    def test_summary_breakdown_matches_clusters(self):
        plan = make_supervisor_plan(store_id="store-A")
        s = supervisor_summary(plan)
        # One row per active cluster
        assert len(s["cluster_breakdown"]) == len(plan.active_clusters)

    def test_summary_totals_add_up(self):
        plan = make_supervisor_plan(store_id="store-A")
        s = supervisor_summary(plan)
        breakdown_fire = sum(
            r["fire"] for r in s["cluster_breakdown"]
        )
        assert breakdown_fire == s["total_to_fire"]


class TestPlanInvariants:

    def test_total_to_fire_is_sum(self):
        plan = make_supervisor_plan(store_id="store-A")
        manual_sum = sum(p.fire_count for p in plan.captain_plans)
        assert plan.total_to_fire == manual_sum

    def test_modifications_routed_to_modifications(self):
        plan = make_supervisor_plan(store_id="store-A")
        # Pricing cluster has 2 modification members
        # (dynamic_pricing + pricing). They should ALWAYS land
        # in modifications_queued, never in members_to_fire.
        pricing_plan = next(
            (p for p in plan.captain_plans if p.cluster == "pricing"),
            None,
        )
        if pricing_plan is None:
            return  # pricing not active
        queued_engines = {
            m["engine"] for m in pricing_plan.modifications_queued
        }
        # At least one of these should be queued (default mode
        # fires all wired, so both should be queued)
        assert "dynamic_pricing" in queued_engines
        # Fired engines should NOT include the modifications
        fired_engines = {
            m["engine"] for m in pricing_plan.members_to_fire
        }
        assert not (queued_engines & fired_engines), (
            "Engine cannot be both queued and fired"
        )
