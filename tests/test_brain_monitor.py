"""Tests for DecisionBrain and RealtimeMonitor."""
import pytest


class TestStoreState:
    def test_basic(self):
        from core.brain.decision_brain import StoreState
        state = StoreState({
            "products": [{"price": 20, "cost": 8, "inventory_quantity": 10}],
            "order_data": [{"total": 50}],
            "customer_data": [{"id": "c1"}],
        })
        assert state.product_count == 1
        assert state.order_count == 1
        assert state.total_revenue == 50
        assert state.avg_margin == 0.6

    def test_health_score(self):
        from core.brain.decision_brain import StoreState
        state = StoreState({"products": [{"price": 20, "cost": 8, "inventory_quantity": 50}] * 12,
                           "order_data": [{"total": 100}],
                           "customer_data": [{}] * 15})
        assert state.health_score > 60

    def test_stockout_detection(self):
        from core.brain.decision_brain import StoreState
        state = StoreState({"products": [
            {"name": "A", "inventory_quantity": 0},
            {"name": "B", "inventory_quantity": 5},
        ]})
        assert len(state.out_of_stock) == 1
        assert len(state.low_stock) == 1


class TestDecisionBrain:
    def test_init(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        assert brain is not None

    def test_think_empty_store(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({"products": [], "order_data": [], "customer_data": []})
        assert "problems" in thought
        assert "action_plan" in thought
        assert len(thought["problems"]) > 0  # Empty store = problems

    def test_think_healthy_store(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        products = [{"name": f"P{i}", "price": 30, "cost": 10, "inventory_quantity": 50} for i in range(15)]
        thought = brain.think({
            "products": products,
            "order_data": [{"total": 100}] * 10,
            "customer_data": [{"id": f"c{i}"} for i in range(20)],
        })
        assert thought["health_score"] > 70

    def test_detects_no_revenue(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({"products": [{"name": "X", "price": 20}], "order_data": [], "customer_data": []})
        problem_types = [p["type"] for p in thought["problems"]]
        assert "no_revenue" in problem_types

    def test_detects_insufficient_products(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({"products": [{"name": "X"}] * 3, "order_data": [], "customer_data": []})
        problem_types = [p["type"] for p in thought["problems"]]
        assert "insufficient_products" in problem_types

    def test_finds_opportunities(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        products = [{"name": f"P{i}", "price": 30, "cost": 8, "category": "home"} for i in range(5)]
        thought = brain.think({"products": products, "order_data": [], "customer_data": []})
        assert len(thought["opportunities"]) > 0

    def test_action_plan_ordered(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({"products": [{"name": "X", "price": 10, "cost": 9}], "order_data": [], "customer_data": []})
        plan = thought["action_plan"]
        if len(plan) > 1:
            assert plan[0]["priority"] <= plan[1]["priority"]

    def test_worldview_exists(self):
        from core.brain.decision_brain import WORLDVIEW
        assert len(WORLDVIEW) >= 10
        assert "profit_first" in WORLDVIEW


class TestRealtimeMonitor:
    def test_init(self):
        from core.system.realtime_monitor import RealtimeMonitor
        mon = RealtimeMonitor()
        assert mon is not None

    def test_status(self):
        from core.system.realtime_monitor import RealtimeMonitor
        mon = RealtimeMonitor()
        status = mon.get_status()
        assert status["running"] is False

    def test_detect_changes_first_check(self):
        from core.system.realtime_monitor import RealtimeMonitor
        mon = RealtimeMonitor()
        changes = mon._detect_changes("test", {"products": [], "order_data": [], "customer_data": []})
        assert len(changes) == 1
        assert changes[0]["type"] == "first_check"

    def test_detect_stockout(self):
        from core.system.realtime_monitor import RealtimeMonitor
        mon = RealtimeMonitor()
        mon._last_state["test"] = {"product_count": 1, "order_count": 0, "customer_count": 0}
        changes = mon._detect_changes("test", {
            "products": [{"name": "Widget", "inventory_quantity": 0}],
            "order_data": [], "customer_data": [],
        })
        types = [c["type"] for c in changes]
        assert "stockout" in types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
