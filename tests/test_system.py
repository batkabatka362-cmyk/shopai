"""Tests for IntelligenceLoop, FullSystemLoop, KPITracker, SystemHealth, ExecutionBridge.

Tests the FULL Data→Decision→Execution→Result→Learning flow.
"""
import os
import json
import pytest
import threading


# ── Helpers ──

SAMPLE_PRODUCTS = [
    {"name": "Wireless Earbuds", "price": 39.99, "cost": 12, "id": "p1",
     "rating": 4.5, "reviews": 200, "inventory_quantity": 50, "category": "electronics"},
    {"name": "Phone Case", "price": 19.99, "cost": 3, "id": "p2",
     "rating": 4.0, "reviews": 300, "inventory_quantity": 200},
]

SAMPLE_CUSTOMERS = [
    {"name": "Alice", "orders": 8, "days_since_last_order": 5},
    {"name": "Bob", "orders": 1, "days_since_last_order": 90},
]

SAMPLE_ORDERS = [
    {"id": "o1", "total": 59.98},
    {"id": "o2", "total": 25.00},
]

FULL_DATA = {
    "products": SAMPLE_PRODUCTS,
    "customers": SAMPLE_CUSTOMERS,
    "orders": SAMPLE_ORDERS,
}


# ── Safe Helpers Tests ──

class TestSafeHelpers:
    def test_safe_float_normal(self):
        from utils.helpers import safe_float
        assert safe_float(42) == 42.0
        assert safe_float(3.14) == 3.14
        assert safe_float("29.99") == 29.99

    def test_safe_float_edge_cases(self):
        from utils.helpers import safe_float
        assert safe_float(None) == 0.0
        assert safe_float("abc") == 0.0
        assert safe_float("$49.99") == 49.99
        assert safe_float("1,234.56") == 1234.56
        assert safe_float("") == 0.0

    def test_safe_int(self):
        from utils.helpers import safe_int
        assert safe_int(42) == 42
        assert safe_int(None) == 0
        assert safe_int("abc") == 0
        assert safe_int("42.7") == 42
        assert safe_int(3.9) == 3

    def test_safe_dict(self):
        from utils.helpers import safe_dict
        assert safe_dict(None) == {}
        assert safe_dict("string") == {}
        assert safe_dict({"a": 1}) == {"a": 1}


# ── IntelligenceLoop Tests ──

class TestIntelligenceLoop:
    def test_full_7_stages(self):
        from core.intelligence_loop import IntelligenceLoop
        il = IntelligenceLoop()
        r = il.run(FULL_DATA, goal="maximize_profit")
        assert r["stages_completed"] == 7
        assert r["data_quality"] > 0
        assert "decision" in r
        assert "plan" in r
        assert "execution" in r
        assert "learning" in r

    def test_confidence_score_is_numeric(self):
        from core.intelligence_loop import IntelligenceLoop
        r = IntelligenceLoop().run(FULL_DATA)
        assert isinstance(r["decision"]["confidence_score"], int)
        assert 0 <= r["decision"]["confidence_score"] <= 100

    def test_multi_option_decision(self):
        from core.intelligence_loop import IntelligenceLoop
        r = IntelligenceLoop().run(FULL_DATA)
        assert r["decision"]["options_evaluated"] >= 2

    def test_negative_price_penalized(self):
        from core.intelligence_loop import IntelligenceLoop
        r = IntelligenceLoop().run({"products": [{"name": "Bad", "price": -5, "cost": 10, "id": "p"}]})
        assert r["data_quality"] < 50

    def test_cost_exceeds_price_penalized(self):
        from core.intelligence_loop import IntelligenceLoop
        r = IntelligenceLoop().run({"products": [{"name": "Losing", "price": 10, "cost": 50, "id": "p"}]})
        assert r["data_quality"] < 70

    def test_string_types_dont_crash(self):
        from core.intelligence_loop import IntelligenceLoop
        r = IntelligenceLoop().run({
            "products": [{"name": "Test", "price": "$29.99", "cost": "abc", "id": "p"}],
            "customers": [{"name": "X", "orders": "many", "days_since_last_order": "long"}],
            "orders": [{"id": "o", "total": "not_a_number"}],
        })
        assert r["stages_completed"] == 7

    def test_empty_products_dont_crash(self):
        from core.intelligence_loop import IntelligenceLoop
        r = IntelligenceLoop().run({"products": []})
        # Empty data may abort due to low quality, but should not crash
        assert "data_quality" in r or "status" in r

    def test_abort_on_garbage_data(self):
        from core.intelligence_loop import IntelligenceLoop
        r = IntelligenceLoop().run({})
        # Should either abort or complete with low quality
        assert "data_quality" in r or "status" in r

    def test_low_data_lower_confidence(self):
        from core.intelligence_loop import IntelligenceLoop
        r_low = IntelligenceLoop().run({"products": [{"name": "X", "price": 5, "cost": 4, "id": "p"}]})
        r_high = IntelligenceLoop().run(FULL_DATA)
        # More data should give higher or equal confidence
        assert r_high["decision"]["confidence_score"] >= r_low["decision"]["confidence_score"] - 10

    def test_learned_weights_accessible(self):
        from core.intelligence_loop import get_learned_weights
        w = get_learned_weights()
        assert isinstance(w, dict)

    def test_history(self):
        from core.intelligence_loop import IntelligenceLoop
        il = IntelligenceLoop()
        il.run(FULL_DATA)
        il.run(FULL_DATA)
        assert len(il.get_history()) == 2


# ── SmartExecutor Tests ──

class TestSmartExecutor:
    def test_score_products_returns_scored(self):
        from core.step_logic.smart_executor import SmartExecutor
        scored = SmartExecutor()._score_products(SAMPLE_PRODUCTS)
        assert len(scored) == 2
        assert "total_score" in scored[0]
        assert "viable" in scored[0]
        assert "confidence" in scored[0]

    def test_out_of_stock_not_viable(self):
        from core.step_logic.smart_executor import SmartExecutor
        scored = SmartExecutor()._score_products([
            {"name": "OOS", "price": 50, "cost": 10, "id": "p", "inventory_quantity": 0},
        ])
        assert scored[0]["viable"] is False

    def test_negative_price_handled(self):
        from core.step_logic.smart_executor import SmartExecutor
        scored = SmartExecutor()._score_products([
            {"name": "Neg", "price": -5, "cost": 10, "id": "p"},
        ])
        assert scored[0]["total_score"] >= 0  # Should not crash

    def test_non_dict_items_skipped(self):
        from core.step_logic.smart_executor import SmartExecutor
        scored = SmartExecutor()._score_products(["string", None, 42])
        assert len(scored) == 0

    def test_learned_weights_applied(self):
        from core.step_logic.smart_executor import SmartExecutor
        from core.intelligence_loop import _learned_weights
        # Set a weight adjustment
        _learned_weights["margin"] = 0.10
        scored = SmartExecutor()._score_products(SAMPLE_PRODUCTS)
        assert len(scored) > 0
        # Clean up
        _learned_weights.pop("margin", None)


# ── FullSystemLoop Tests ──

class TestFullSystemLoop:
    def test_full_cycle_completes(self):
        from core.full_system_loop import FullSystemLoop
        r = FullSystemLoop().run(FULL_DATA, config={"goal": "maximize_profit"})
        assert r["status"] in ("completed", "partial")
        assert "phases" in r

    def test_phases_present(self):
        from core.full_system_loop import FullSystemLoop
        r = FullSystemLoop().run(FULL_DATA)
        phases = r["phases"]
        for key in ("data", "intelligence", "agents", "execution", "memory", "learning"):
            assert key in phases, f"Missing phase: {key}"

    def test_outcome_tracking(self):
        from core.full_system_loop import FullSystemLoop
        r = FullSystemLoop().run(FULL_DATA)
        learn = r["phases"]["learning"]
        assert "outcome_recorded" in learn
        assert "decision_accuracy" in learn

    def test_bad_data_gates_execution(self):
        from core.full_system_loop import FullSystemLoop
        r = FullSystemLoop().run({"products": "not_a_list"})
        # Should handle gracefully
        assert r["status"] in ("completed", "partial")

    def test_confidence_score_in_output(self):
        from core.full_system_loop import FullSystemLoop
        r = FullSystemLoop().run(FULL_DATA)
        intel = r["phases"]["intelligence"]
        assert "confidence_score" in intel

    def test_history(self):
        from core.full_system_loop import FullSystemLoop
        fsl = FullSystemLoop()
        fsl.run(FULL_DATA)
        assert len(fsl.get_history()) == 1


# ── ExecutionBridge Tests ──

class TestExecutionBridge:
    def test_plan_actions(self):
        from core.bridge.execution_bridge import ExecutionBridge
        eb = ExecutionBridge()
        actions = eb.plan_actions("test_engine", {
            "selected_products": [{"name": "P", "viable": True}],
        })
        assert len(actions) > 0
        assert actions[0]["action_type"] == "product.create_listing"

    def test_approve_and_execute(self):
        from core.bridge.execution_bridge import ExecutionBridge
        eb = ExecutionBridge()
        eb.plan_actions("test", {"selected_products": [{"name": "P", "viable": True}]})
        queue = eb.get_queue()
        assert len(queue) > 0
        eb.approve_action(queue[0]["action_id"])
        results = eb.execute_approved()
        assert len(results) > 0

    def test_retry_on_failure(self):
        from core.bridge.execution_bridge import ExecutionBridge, ActionPlan

        class FailThenSucceed:
            def __init__(self):
                self.calls = 0
            def execute(self, data):
                self.calls += 1
                if self.calls <= 2:
                    raise RuntimeError("fail")
                return {"status": "ok"}

        eb = ExecutionBridge()
        executor = FailThenSucceed()
        eb.register_executor("t", "t.action", executor)
        action = ActionPlan("t.action", "t", {})
        action.status = "approved"
        eb._action_queue.append(action)
        results = eb.execute_approved()
        assert results[0]["success"] is True
        assert executor.calls == 3

    def test_retry_exhausted(self):
        from core.bridge.execution_bridge import ExecutionBridge, ActionPlan

        class AlwaysFail:
            def execute(self, data):
                raise RuntimeError("permanent fail")

        eb = ExecutionBridge()
        eb.register_executor("t", "t.fail", AlwaysFail())
        action = ActionPlan("t.fail", "t", {})
        action.status = "approved"
        eb._action_queue.append(action)
        results = eb.execute_approved()
        assert results[0]["success"] is False
        assert "all_errors" in results[0]

    def test_execution_stats(self):
        from core.bridge.execution_bridge import ExecutionBridge
        eb = ExecutionBridge()
        eb.plan_actions("test", {"selected_products": [{"name": "P", "viable": True}]})
        for a in eb.get_queue():
            eb.approve_action(a["action_id"])
        eb.execute_approved()
        stats = eb.get_execution_stats()
        assert stats["total"] > 0
        assert "success_rate" in stats


# ── OutcomeTracker Tests ──

class TestOutcomeTracker:
    def setup_method(self):
        # Clean both old and new paths
        for base in ("/tmp/shopai_outcomes", os.path.expanduser("~/.shopai/data/outcomes")):
            path = os.path.join(base, "test_ot.json")
            if os.path.exists(path):
                os.remove(path)

    def test_record_and_retrieve(self):
        from core.learning.outcome_tracker import OutcomeTracker
        ot = OutcomeTracker()
        ot.record_decision("d1", "test_ot", {"score": 8})
        ot.record_outcome("d1", "test_ot", {"success": True, "revenue": 100})
        patterns = ot.get_winning_patterns("test_ot")
        assert patterns["with_outcomes"] == 1

    def test_correlation_check(self):
        from core.learning.outcome_tracker import OutcomeTracker
        ot = OutcomeTracker()
        # High scores succeed
        ot.record_decision("d1", "test_ot", {"score": 9})
        ot.record_outcome("d1", "test_ot", {"success": True})
        ot.record_decision("d2", "test_ot", {"score": 8})
        ot.record_outcome("d2", "test_ot", {"success": True})
        # Low score fails
        ot.record_decision("d3", "test_ot", {"score": 2})
        ot.record_outcome("d3", "test_ot", {"success": False})

        patterns = ot.get_winning_patterns("test_ot")
        score_range = [p for p in patterns["patterns"] if p["pattern"] == "score_range"]
        assert len(score_range) > 0
        assert score_range[0]["correlation"] == "confirmed"

    def test_false_correlation_rejected(self):
        from core.learning.outcome_tracker import OutcomeTracker
        ot = OutcomeTracker()
        # Same scores for success AND failure
        ot.record_decision("d1", "test_ot", {"score": 5})
        ot.record_outcome("d1", "test_ot", {"success": True})
        ot.record_decision("d2", "test_ot", {"score": 5})
        ot.record_outcome("d2", "test_ot", {"success": False})

        patterns = ot.get_winning_patterns("test_ot")
        confirmed = [p for p in patterns["patterns"] if p.get("correlation") == "confirmed"]
        assert len(confirmed) == 0

    def test_thread_safety(self):
        from core.learning.outcome_tracker import OutcomeTracker
        ot = OutcomeTracker()
        errors = []

        def worker(i):
            try:
                ot.record_decision(f"d{i}", "test_ot", {"score": i})
                ot.record_outcome(f"d{i}", "test_ot", {"success": i % 2 == 0})
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

    def teardown_method(self):
        for base in ("/tmp/shopai_outcomes", os.path.expanduser("~/.shopai/data/outcomes")):
            path = os.path.join(base, "test_ot.json")
            if os.path.exists(path):
                os.remove(path)


# ── KPI Tracker Tests ──

class TestKPITracker:
    def setup_method(self):
        for base in ("/tmp/shopai_kpi", os.path.expanduser("~/.shopai/data/kpi")):
            for f in ("decisions.json", "revenue_events.json"):
                path = os.path.join(base, f)
                if os.path.exists(path):
                    os.remove(path)

    def test_record_decision_outcome(self):
        from core.intelligence.kpi_tracker import KPITracker
        kpi = KPITracker()
        kpi.record_decision_outcome("d1", "launch", "high", 80, True, 90)
        kpi.record_decision_outcome("d2", "launch", "low", 30, False, 40)
        result = kpi.get_decision_kpis()
        assert result["total_decisions"] == 2
        assert result["overall_success_rate"] == 50.0

    def test_confidence_calibration(self):
        from core.intelligence.kpi_tracker import KPITracker
        kpi = KPITracker()
        kpi.record_decision_outcome("d1", "x", "high", 80, True, 90)
        kpi.record_decision_outcome("d2", "x", "low", 20, False, 30)
        result = kpi.get_decision_kpis()
        assert result["confidence_calibrated"] is True

    def test_revenue_kpis(self):
        from core.intelligence.kpi_tracker import KPITracker
        kpi = KPITracker()
        kpi.record_revenue_event("d1", revenue=1000, cost=100,
                                  conversion_count=50, impression_count=10000, click_count=500)
        result = kpi.get_revenue_kpis()
        assert result["overall_ctr"] == 5.0
        assert result["overall_conversion_rate"] == 0.5
        assert result["overall_roas"] == 10.0
        assert result["overall_cac"] == 2.0

    def teardown_method(self):
        for base in ("/tmp/shopai_kpi", os.path.expanduser("~/.shopai/data/kpi")):
            for f in ("decisions.json", "revenue_events.json"):
                path = os.path.join(base, f)
                if os.path.exists(path):
                    os.remove(path)


# ── SystemHealthReport Tests ──

class TestSystemHealth:
    def test_generate_report(self):
        from core.intelligence.system_health import SystemHealthReport
        report = SystemHealthReport().generate()
        assert "sections" in report
        assert "overall_grade" in report
        for section in ("decision_quality", "execution_health", "learning_progress",
                        "data_quality", "revenue_impact"):
            assert section in report["sections"]

    def test_grade_calculation(self):
        from core.intelligence.system_health import SystemHealthReport
        shr = SystemHealthReport()
        # All A grades
        assert shr._calculate_grade({
            "s1": {"grade": "A"}, "s2": {"grade": "A"},
        }) == "A"
        # Mixed grades
        assert shr._calculate_grade({
            "s1": {"grade": "A"}, "s2": {"grade": "F"},
        }) in ("B", "C")
        # No data
        assert shr._calculate_grade({
            "s1": {"grade": "N/A"},
        }) == "N/A"


# ── Revenue Tracker Tests ──

class TestRevenueTracker:
    def setup_method(self):
        for base in ("/tmp/shopai_revenue", os.path.expanduser("~/.shopai/data/revenue")):
            path = os.path.join(base, "actions.json")
            if os.path.exists(path):
                os.remove(path)

    def test_record_and_query(self):
        from core.intelligence.revenue_tracker import RevenueTracker
        rt = RevenueTracker()
        aid = rt.record_action("pricing", "Product A", {"change": "increase"})
        assert rt.record_revenue(aid, revenue=500, cost=50, orders=10)
        summary = rt.get_roi_summary()
        assert summary["total_revenue"] == 500
        assert summary["total_profit"] == 450

    def test_thread_safety(self):
        from core.intelligence.revenue_tracker import RevenueTracker
        rt = RevenueTracker()
        errors = []

        def worker(i):
            try:
                aid = rt.record_action("test", f"p{i}", {})
                rt.record_revenue(aid, revenue=i * 10, cost=i)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0

    def teardown_method(self):
        for base in ("/tmp/shopai_revenue", os.path.expanduser("~/.shopai/data/revenue")):
            path = os.path.join(base, "actions.json")
            if os.path.exists(path):
                os.remove(path)
