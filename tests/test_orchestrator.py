"""Tests for engines._orchestrator (Tier 1)."""
from __future__ import annotations

from engines._orchestrator import (
    FleetPlan,
    StorePriority,
    DeterministicOrchestratorStrategy,
    make_fleet_plan,
    fleet_summary,
)


class TestDeterministicPriorityRules:

    def _strat(self):
        return DeterministicOrchestratorStrategy()

    def test_no_products_is_launching(self):
        prio = self._strat().decide_priority(
            "store-A", {"stats": {"products": 0, "orders": 0}},
        )
        assert prio.priority == "launching"
        assert "setup" in prio.cluster_focus

    def test_few_products_is_launching(self):
        prio = self._strat().decide_priority(
            "store-A",
            {"stats": {"products": 3, "orders": 5}},
        )
        assert prio.priority == "launching"

    def test_zero_orders_is_launching(self):
        prio = self._strat().decide_priority(
            "store-A",
            {"stats": {"products": 100, "orders": 0}},
        )
        assert prio.priority == "launching"

    def test_low_avg_order_is_at_risk(self):
        # orders > 5, low avg
        prio = self._strat().decide_priority(
            "store-A",
            {"stats": {
                "products": 50, "orders": 10,
                "total_revenue": 50.0,  # $5 avg
            }},
        )
        assert prio.priority == "at_risk"

    def test_high_order_count_is_mature(self):
        prio = self._strat().decide_priority(
            "store-A",
            {"stats": {
                "products": 100, "orders": 100,
                "total_revenue": 10000.0,  # $100 avg
            }},
        )
        assert prio.priority == "mature"
        assert "retention" in prio.cluster_focus

    def test_middle_is_growing(self):
        prio = self._strat().decide_priority(
            "store-A",
            {"stats": {
                "products": 30, "orders": 20,
                "total_revenue": 1000.0,
            }},
        )
        assert prio.priority == "growing"

    def test_empty_world_model_is_launching(self):
        # No stats at all -> launching (defensive default)
        prio = self._strat().decide_priority("store-A", {})
        assert prio.priority == "launching"


class TestFleetPlan:

    def test_empty_fleet(self):
        plan = make_fleet_plan(world_models={})
        assert plan.total_stores == 0
        assert plan.total_to_fire == 0
        assert any("empty" in n for n in plan.notes)

    def test_single_mature_store(self):
        plan = make_fleet_plan(world_models={
            "store-A": {"stats": {
                "products": 100, "orders": 100,
                "total_revenue": 10000.0,
            }},
        })
        assert plan.total_stores == 1
        assert plan.priorities[0].priority == "mature"
        # MATURE priority focus: retention, pricing, merchandising
        active = plan.supervisor_plans[0].active_clusters
        assert set(active) == {
            "retention", "pricing", "merchandising",
        }

    def test_mixed_fleet(self):
        plan = make_fleet_plan(world_models={
            "store-launching": {"stats": {
                "products": 2, "orders": 0,
            }},
            "store-mature": {"stats": {
                "products": 100, "orders": 100,
                "total_revenue": 10000.0,
            }},
        })
        assert plan.total_stores == 2
        priorities = {
            p.store_id: p.priority for p in plan.priorities
        }
        assert priorities["store-launching"] == "launching"
        assert priorities["store-mature"] == "mature"

    def test_priorities_have_rationale(self):
        plan = make_fleet_plan(world_models={
            "store-A": {"stats": {
                "products": 100, "orders": 100,
                "total_revenue": 10000.0,
            }},
        })
        assert plan.priorities[0].rationale  # non-empty


class TestSummary:

    def test_summary_shape(self):
        plan = make_fleet_plan(world_models={
            "store-A": {"stats": {"products": 0, "orders": 0}},
            "store-B": {"stats": {
                "products": 100, "orders": 100,
                "total_revenue": 10000.0,
            }},
        })
        s = fleet_summary(plan)
        assert s["total_stores"] == 2
        assert len(s["stores"]) == 2
        for row in s["stores"]:
            assert "store_id" in row
            assert "priority" in row
            assert "rationale" in row
            assert "fire" in row


class TestStrategyPluggable:

    def test_custom_strategy_overrides_priority(self):
        class AlwaysAtRiskStrategy:
            def decide_priority(self, store_id, world_model):
                return StorePriority(
                    store_id=store_id,
                    priority="at_risk",
                    cluster_focus=["retention", "discovery"],
                    rationale="custom strategy says at_risk",
                )

        plan = make_fleet_plan(
            world_models={
                "store-A": {"stats": {
                    "products": 1000, "orders": 1000,
                    "total_revenue": 100000.0,
                }},
            },
            strategy=AlwaysAtRiskStrategy(),
        )
        # Despite being a mature store by stats, custom
        # strategy forces at_risk
        assert plan.priorities[0].priority == "at_risk"
        active = plan.supervisor_plans[0].active_clusters
        assert "retention" in active
