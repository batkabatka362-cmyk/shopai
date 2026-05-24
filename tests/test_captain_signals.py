"""Tests for engines._captain_signals."""
from __future__ import annotations

from engines._captain_signals import (
    HeuristicSignalCollector,
    collect_signals_for_store,
)


class TestHeuristicCollector:

    def _collect(self, world_model, queue_stats=None):
        return HeuristicSignalCollector().collect(
            "store-A", world_model, queue_stats or {},
        )

    def test_launching_store_signals(self):
        signals = self._collect({
            "stats": {"products": 2, "orders": 0, "customers": 0},
        })
        # Setup gets first_launch signal
        assert signals["setup"]["first_launch"] is True
        # acquisition triggers on low customer count
        assert signals["acquisition"]["new_signups_count"] == 1

    def test_mature_store_signals(self):
        signals = self._collect({
            "stats": {
                "products": 100, "orders": 200,
                "customers": 80, "total_revenue": 5000.0,
            },
        })
        # Retention should have at_risk_count derived from
        # customer count
        assert signals["retention"]["at_risk_count"] >= 1
        # Quality should have defect_count from orders >100
        assert signals["quality"]["defect_count"] >= 1
        # Pricing should detect potential thin margin
        assert "thin_margin_count" in signals["pricing"]

    def test_empty_store_returns_minimal_signals(self):
        signals = self._collect({})
        # No stats -> setup + acquisition still get default
        # signals because heuristics handle absent stats
        assert "setup" in signals
        assert "acquisition" in signals
        # retention won't appear (no customers)
        assert "retention" not in signals

    def test_every_cluster_has_entry_for_realistic_store(self):
        signals = self._collect({
            "stats": {
                "products": 50, "orders": 30,
                "customers": 25, "total_revenue": 2000.0,
            },
        })
        # All clusters should be in the output
        expected = {
            "retention", "pricing", "quality", "fulfillment",
            "merchandising", "acquisition", "discovery",
            "governance", "content",
        }
        # setup may be absent (orders > 0, products >= 5)
        assert set(signals.keys()) >= expected


class TestPluggable:

    def test_custom_strategy(self):
        class FixedSignals:
            def collect(self, store_id, world_model, queue_stats):
                return {
                    "retention": {"at_risk_count": 100},
                    "pricing": {},
                }

        signals = collect_signals_for_store(
            "store-A",
            world_model={"stats": {}},
            queue_stats={},
            strategy=FixedSignals(),
        )
        assert signals["retention"]["at_risk_count"] == 100


class TestEndToEndWithSupervisor:
    """Signals collected -> supervisor -> captains use them."""

    def test_signals_propagate_to_captain_selection(self):
        from engines._store_supervisor import (
            make_supervisor_plan,
        )

        signals = collect_signals_for_store(
            "store-A",
            world_model={"stats": {
                "products": 50, "orders": 100,
                "customers": 80, "total_revenue": 8000.0,
            }},
            queue_stats={},
        )

        plan = make_supervisor_plan(
            store_id="store-A",
            signals_by_cluster=signals,
        )

        # retention captain should fire something because
        # signals include at_risk_count
        retention_plan = next(
            (p for p in plan.captain_plans
             if p.cluster == "retention"),
            None,
        )
        assert retention_plan is not None
        # Captain saw at_risk signal -> fired churn-focused
        fired = {m["engine"] for m in retention_plan.members_to_fire}
        assert len(fired) > 0
