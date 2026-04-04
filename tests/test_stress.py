"""Stress tests — push system to limits."""
import unittest
import random
import threading


class TestStress(unittest.TestCase):
    """Stress test engines under extreme conditions."""

    def test_empty_data_all_engines(self):
        """50 engines with completely empty data — none should crash."""
        from engines.registry import list_engines, get_engine
        sample = random.sample(list_engines(), min(50, len(list_engines())))
        for name in sample:
            e = get_engine(name)
            result = e.run({"status": "success", "data": {}, "meta": {}, "error": None})
            self.assertIn(result["status"], ["success", "error", "fail"],
                          f"{name} crashed on empty data")

    def test_none_input(self):
        """Engines with None data — should return error, not crash."""
        from engines.registry import list_engines, get_engine
        sample = random.sample(list_engines(), 30)
        for name in sample:
            e = get_engine(name)
            result = e.run({"status": "success", "data": None, "meta": {}, "error": None})
            self.assertIn(result["status"], ["success", "error", "fail"])

    def test_upstream_failure_propagation(self):
        """All engines should propagate upstream failures."""
        from engines.registry import list_engines, get_engine
        sample = random.sample(list_engines(), 30)
        for name in sample:
            e = get_engine(name)
            result = e.run({"status": "fail", "data": {}, "meta": {}, "error": "Upstream failed"})
            self.assertIn(result["status"], ["error", "fail"], f"{name} didn't propagate upstream failure")

    def test_concurrent_engines(self):
        """10 engines running in parallel — thread safety."""
        from engines.registry import list_engines, get_engine
        results = []
        errors = []

        def run_engine(name):
            try:
                e = get_engine(name)
                out = e.run({"status": "success", "data": {}, "meta": {}, "error": None})
                results.append(out["status"])
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        sample = random.sample(list_engines(), 10)
        threads = [threading.Thread(target=run_engine, args=(n,)) for n in sample]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        self.assertEqual(len(errors), 0, f"Concurrent errors: {errors}")
        self.assertEqual(len(results), 10)

    def test_repeated_execution(self):
        """Same engine 20 times — consistent results."""
        from engines.registry import get_engine
        e = get_engine("pricing")
        statuses = set()
        for i in range(20):
            out = e.run({"status": "success", "data": {
                "products": [{"name": "X", "price": 30, "cost": 10}],
            }, "meta": {}, "error": None})
            statuses.add(out["status"])
        self.assertEqual(len(statuses), 1, f"Inconsistent: {statuses}")

    def test_all_engines_load(self):
        """All registered engines must load and have run()."""
        from engines.registry import list_engines, get_engine
        failed = []
        for name in list_engines():
            e = get_engine(name)
            if e is None or not hasattr(e, "run"):
                failed.append(name)
        self.assertEqual(len(failed), 0, f"Failed to load: {failed}")


class TestDataIntegrity(unittest.TestCase):
    """Test data integrity system."""

    def test_clean_products(self):
        from core.data_context.data_integrity import DataIntegrity
        di = DataIntegrity()
        result = di.validate_products([
            {"name": "Good", "price": 30, "cost": 8},
            {"name": "", "price": -5},
            {"name": "String Price", "price": "$49.99", "cost": 15},
            {"price": 20},
        ])
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["invalid_count"], 2)

    def test_clean_customers(self):
        from core.data_context.data_integrity import DataIntegrity
        di = DataIntegrity()
        result = di.validate_customers([
            {"name": "Alice", "orders": 5, "total_spent": 200},
            {"name": "Bob", "orders": "3", "total_spent": "$150"},
        ])
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["valid"][1]["orders"], 3)

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
