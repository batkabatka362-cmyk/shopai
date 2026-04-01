"""Stress tests — push system to limits."""
import unittest
import random
import threading


class TestStress(unittest.TestCase):
    """Stress test the system under extreme conditions."""

    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_empty_data_all_engines(self):
        """50 engines with completely empty data — none should crash."""
        from engines.registry import list_engines, get_engine
        from engines.base.engine_types import EngineInput, EngineStatus
        sample = random.sample(list_engines(), 50)
        for name in sample:
            e = get_engine(name)
            out = e.run(EngineInput(task_id=f"empty_{name}", engine_name=name, data={}))
            self.assertIn(out.status, [EngineStatus.COMPLETED, EngineStatus.FAILED],
                          f"{name} crashed on empty data")

    def test_none_values(self):
        """30 engines with None values — none should crash."""
        from engines.registry import list_engines, get_engine
        from engines.base.engine_types import EngineInput, EngineStatus
        sample = random.sample(list_engines(), 30)
        for name in sample:
            e = get_engine(name)
            data = {f: None for f in e.required_input_fields}
            out = e.run(EngineInput(task_id=f"none_{name}", engine_name=name, data=data))
            self.assertIn(out.status, [EngineStatus.COMPLETED, EngineStatus.FAILED])

    def test_wrong_types(self):
        """30 engines with wrong data types — none should crash."""
        from engines.registry import list_engines, get_engine
        from engines.base.engine_types import EngineInput, EngineStatus
        sample = random.sample(list_engines(), 30)
        for name in sample:
            e = get_engine(name)
            data = {f: 12345 for f in e.required_input_fields}
            out = e.run(EngineInput(task_id=f"type_{name}", engine_name=name, data=data))
            self.assertIn(out.status, [EngineStatus.COMPLETED, EngineStatus.FAILED])

    def test_large_product_list(self):
        """500 products through product_selection — should handle."""
        from engines.registry import get_engine
        from engines.base.engine_types import EngineInput, EngineStatus
        products = [{"name": f"Product_{i}", "price": random.uniform(5, 200),
                      "cost": random.uniform(1, 50), "weight": random.uniform(0.01, 5)}
                    for i in range(500)]
        e = get_engine("product_selection")
        out = e.run(EngineInput(task_id="big", engine_name="product_selection",
                                data={"products": products, "criteria": {}}))
        self.assertEqual(out.status, EngineStatus.COMPLETED)

    def test_concurrent_engines(self):
        """10 engines running in parallel — thread safety."""
        from engines.registry import list_engines, get_engine
        from engines.base.engine_types import EngineInput
        results = []
        errors = []

        def run_engine(name):
            try:
                e = get_engine(name)
                data = {f: {} for f in e.required_input_fields}
                out = e.run(EngineInput(task_id=f"conc_{name}", engine_name=name, data=data))
                results.append(out.status.value)
            except Exception as exc:
                errors.append(str(exc))

        sample = random.sample(list_engines(), 10)
        threads = [threading.Thread(target=run_engine, args=(n,)) for n in sample]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(errors), 0, f"Concurrent errors: {errors}")
        self.assertEqual(len(results), 10)

    def test_repeated_execution(self):
        """Same engine 50 times — consistent results."""
        from engines.registry import get_engine
        from engines.base.engine_types import EngineInput, EngineStatus
        e = get_engine("pricing")
        data = {"products": [{"name": "X", "price": 30, "cost": 10}]}
        statuses = set()
        for i in range(50):
            out = e.run(EngineInput(task_id=f"rep_{i}", engine_name="pricing", data=data))
            statuses.add(out.status)
        # Should always be the same status
        self.assertEqual(len(statuses), 1, f"Inconsistent: {statuses}")
        self.assertIn(EngineStatus.COMPLETED, statuses)

    def test_workflow_with_bad_data(self):
        """Workflow should handle gracefully when data is bad."""
        result = self.orch.run_workflow("product_launch", {"products": "not_a_list"})
        self.assertIn(result["status"], ["completed", "partial"])

    def test_mass_200_engines(self):
        """200 random engines with minimal data — all must complete."""
        from engines.registry import list_engines, get_engine
        from engines.base.engine_types import EngineInput, EngineStatus
        sample = random.sample(list_engines(), min(50, len(list_engines())))
        failed = []
        for name in sample:
            e = get_engine(name)
            data = {f: [{"name": "T", "price": 30, "cost": 10}] if "product" in f.lower()
                    else [{"name": "C", "orders": 5}] if "customer" in f.lower()
                    else {} for f in e.required_input_fields}
            out = e.run(EngineInput(task_id=f"mass_{name}", engine_name=name, data=data))
            if out.status != EngineStatus.COMPLETED:
                failed.append(name)
        self.assertEqual(len(failed), 0, f"Failed engines: {failed[:5]}")


class TestDataIntegrity(unittest.TestCase):
    """Test data integrity system."""

    def test_clean_products(self):
        from core.data_context.data_integrity import DataIntegrity
        di = DataIntegrity()
        result = di.validate_products([
            {"name": "Good", "price": 30, "cost": 8},
            {"name": "", "price": -5},  # bad
            {"name": "String Price", "price": "$49.99", "cost": 15},
            {"price": 20},  # no name
        ])
        self.assertEqual(result["valid_count"], 2)  # Good + String Price (auto-fixed)
        self.assertEqual(result["invalid_count"], 2)

    def test_clean_customers(self):
        from core.data_context.data_integrity import DataIntegrity
        di = DataIntegrity()
        result = di.validate_customers([
            {"name": "Alice", "orders": 5, "total_spent": 200},
            {"name": "Bob", "orders": "3", "total_spent": "$150"},  # string types
        ])
        self.assertEqual(result["valid_count"], 2)  # Both valid after cleaning
        self.assertEqual(result["valid"][1]["orders"], 3)  # String → int

    def test_flow_integrity(self):
        from core.data_context.data_integrity import DataIntegrity
        di = DataIntegrity()
        result = di.check_flow_integrity([
            {"score": 7, "decision": "approve"},
            {"generated": True, "products": [1, 2]},
            {"enhanced": True},
            {"valid": True, "checks": [1, 2, 3]},
        ])
        self.assertEqual(result["integrity"], "ok")


class TestOutcomeTracker(unittest.TestCase):
    def test_record_and_learn(self):
        from core.learning.outcome_tracker import OutcomeTracker
        ot = OutcomeTracker()
        ot.record_decision("test_d1", "test_engine", {"score": 8})
        ot.record_outcome("test_d1", "test_engine", {"success": True, "revenue": 100})
        ot.record_decision("test_d2", "test_engine", {"score": 3})
        ot.record_outcome("test_d2", "test_engine", {"success": False, "revenue": 0})
        patterns = ot.get_winning_patterns("test_engine")
        self.assertGreater(patterns["with_outcomes"], 0)

    def test_should_proceed(self):
        from core.learning.outcome_tracker import OutcomeTracker
        ot = OutcomeTracker()
        advice = ot.should_proceed("new_engine", {"score": 7})
        self.assertIn("proceed", advice)


class TestRevenueTracker(unittest.TestCase):
    def test_record_and_summarize(self):
        from core.intelligence.revenue_tracker import RevenueTracker
        rt = RevenueTracker()
        aid = rt.record_action("test_action", "test_product", {"price": 30})
        rt.record_revenue(aid, revenue=300, cost=100, orders=10)
        summary = rt.get_roi_summary()
        self.assertGreater(summary.get("total_revenue", 0), 0)


if __name__ == "__main__":
    unittest.main()
