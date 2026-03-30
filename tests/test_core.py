"""Test suite for core modules."""
import unittest
import time


class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_submit_task(self):
        result = self.orch.submit_task("pricing", {"products": [{"name": "X", "price": 30, "cost": 8}]})
        self.assertEqual(result["status"], "completed")
        self.assertIn("elapsed_seconds", result)

    def test_submit_unknown_task(self):
        result = self.orch.submit_task("totally_nonexistent_xyz")
        self.assertEqual(result["status"], "failed")

    def test_submit_when_not_running(self):
        from core.orchestrator import MainOrchestrator
        orch2 = MainOrchestrator()
        result = orch2.submit_task("pricing")
        self.assertEqual(result["status"], "error")

    def test_get_status(self):
        status = self.orch.get_status()
        self.assertTrue(status["running"])
        self.assertIn("metrics", status)

    def test_health_check(self):
        health = self.orch.health_check()
        self.assertEqual(health["status"], "healthy")

    def test_create_session(self):
        sid = self.orch.create_session()
        self.assertTrue(sid.startswith("sess_"))


class TestAgentBridge(unittest.TestCase):
    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_list_agents(self):
        agents = self.orch.list_agents()
        self.assertGreaterEqual(len(agents), 6)

    def test_agent_run(self):
        result = self.orch.agent_run("product_agent", "pricing", {"products": [{"name": "X", "price": 30, "cost": 8}]})
        self.assertEqual(result["status"], "completed")
        self.assertIn("_agent", result)

    def test_unknown_agent(self):
        result = self.orch.agent_run("fake_agent_xyz", "task", {})
        self.assertIn("error", result)


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_list_workflows(self):
        wfs = self.orch.list_workflows()
        self.assertGreaterEqual(len(wfs), 6)

    def test_run_workflow(self):
        result = self.orch.run_workflow("product_launch", {
            "products": [{"name": "Test", "price": 30, "cost": 10}], "criteria": {},
        })
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["completed_steps"], result["total_steps"])


class TestDataContext(unittest.TestCase):
    def test_data_context_prepare(self):
        from core.data_context import DataContext
        ctx = DataContext({"products": [{"name": "X", "price": "$29.99", "cost": 10}]})
        ctx.prepare()
        self.assertGreater(len(ctx.features), 0)

    def test_pipeline_validator(self):
        from core.data_context import PipelineValidator
        pv = PipelineValidator()
        result = pv.validate_products([
            {"name": "Good", "price": 30, "cost": 8},
            {"name": "", "price": -5},
        ])
        self.assertEqual(result["valid"], 1)
        self.assertEqual(result["invalid"], 1)

    def test_auto_repair(self):
        from core.data_context import PipelineValidator
        pv = PipelineValidator()
        result = pv.validate({"price": "$49.99", "quantity": 5.0})
        self.assertGreater(result["repair_count"], 0)


class TestLearning(unittest.TestCase):
    def test_feedback_store(self):
        from core.learning import FeedbackStore
        fs = FeedbackStore()
        fb_id = fs.record("test_engine", "t1", "completed", 0.5, quality_score=8.0)
        self.assertTrue(fb_id.startswith("fb_"))
        stats = fs.get_stats("test_engine")
        self.assertGreater(stats["total_runs"], 0)

    def test_learning_engine(self):
        from core.learning import FeedbackStore, LearningEngine
        fs = FeedbackStore()
        fs.record("test_le", "t1", "completed", 0.5)
        le = LearningEngine(fs)
        analysis = le.analyze("test_le")
        self.assertIn("risk_level", analysis)


class TestEvents(unittest.TestCase):
    def test_pub_sub(self):
        from core.events import EventBus, EventType
        bus = EventBus()
        received = []
        bus.subscribe(EventType.ENGINE_COMPLETE, "test_sub", lambda e: received.append(e.source))
        bus.emit(EventType.ENGINE_COMPLETE, "test_source")
        self.assertEqual(received, ["test_source"])

    def test_stats(self):
        from core.events import EventBus
        bus = EventBus()
        stats = bus.get_stats()
        self.assertIn("published", stats)


class TestTelemetry(unittest.TestCase):
    def test_tracer(self):
        from core.telemetry import Tracer
        tracer = Tracer()
        span = tracer.start_trace("test_trace")
        tracer.finish_span(span)
        summary = tracer.get_trace_summary(span.trace_id)
        self.assertEqual(summary["total_spans"], 1)

    def test_metrics(self):
        from core.telemetry import MetricsCollector
        mc = MetricsCollector()
        mc.increment("test_counter", 5)
        self.assertEqual(mc.get_counter("test_counter"), 5)
        mc.histogram("test_hist", 100)
        stats = mc.get_histogram_stats("test_hist")
        self.assertEqual(stats["count"], 1)


class TestPerformance(unittest.TestCase):
    def test_execution_cache(self):
        from core.performance import ExecutionCache
        cache = ExecutionCache()
        cache.store("test_eng", {"key": "val"}, {"result": "cached"})
        hit = cache.get("test_eng", {"key": "val"})
        self.assertIsNotNone(hit)
        miss = cache.get("test_eng", {"key": "other"})
        self.assertIsNone(miss)


class TestErrorIntelligence(unittest.TestCase):
    def test_classify(self):
        from core.error_intelligence import ErrorClassifier
        ec = ErrorClassifier()
        r = ec.classify("Missing required field: products")
        self.assertEqual(r["category"], "input_validation")
        self.assertTrue(r["recoverable"])

    def test_fix_suggest(self):
        from core.error_intelligence import FixSuggester
        fs = FixSuggester()
        fix = fs.suggest("connection refused")
        self.assertGreater(len(fix["suggestions"]), 0)


class TestRateLimiter(unittest.TestCase):
    def test_rate_limit(self):
        from core.rate_limiter import RateLimiter
        rl = RateLimiter()
        rl.configure("test_rl", rate=100, burst=3)
        self.assertTrue(rl.allow("test_rl"))
        self.assertTrue(rl.allow("test_rl"))

    def test_quota(self):
        from core.rate_limiter import QuotaManager
        qm = QuotaManager()
        qm.set_quota("test_q", limit=10, period_seconds=3600)
        self.assertTrue(qm.consume("test_q", 5))
        status = qm.check("test_q")
        self.assertEqual(status["used"], 5)
        self.assertEqual(status["remaining"], 5)


class TestShopifyBridge(unittest.TestCase):
    def test_mock_products(self):
        from core.bridge.shopify_bridge import ShopifyBridge
        sb = ShopifyBridge()
        products = sb.fetch_products()
        self.assertGreater(len(products), 0)
        self.assertIn("name", products[0])
        self.assertIn("price", products[0])

    def test_fetch_for_engine(self):
        from core.bridge.shopify_bridge import ShopifyBridge
        sb = ShopifyBridge()
        data = sb.fetch_for_engine("product_selection")
        self.assertIn("products", data)


class TestComputation(unittest.TestCase):
    def test_margin(self):
        from core.step_logic import Computation as C
        self.assertEqual(C.margin(100, 40), 60.0)
        self.assertEqual(C.margin(0, 10), 0.0)

    def test_ltv(self):
        from core.step_logic import Computation as C
        self.assertEqual(C.ltv(50, 4, 3), 600)

    def test_roas(self):
        from core.step_logic import Computation as C
        self.assertEqual(C.roas(5000, 1000), 5.0)

    def test_rfm(self):
        from core.step_logic import Computation as C
        rfm = C.rfm_score(15, 8, 350)
        self.assertEqual(rfm["recency"], 5)
        self.assertEqual(rfm["frequency"], 5)

    def test_break_even(self):
        from core.step_logic import Computation as C
        units = C.break_even_units(10000, 30, 8)
        self.assertEqual(units, 455)


if __name__ == "__main__":
    unittest.main()
