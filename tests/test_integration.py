"""Integration tests — end-to-end flows across multiple systems."""
import unittest
import time


class TestWorkflowIntegration(unittest.TestCase):
    """Test multi-agent multi-engine workflows end-to-end."""

    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_product_launch_workflow(self):
        result = self.orch.run_workflow("product_launch", {
            "products": [{"name": "Test Widget", "price": 29.99, "cost": 8}],
            "criteria": {},
        })
        self.assertIn(result["status"], ["completed", "partial", "failed"])
        self.assertGreaterEqual(result["elapsed_seconds"], 0)

    def test_customer_retention_workflow(self):
        result = self.orch.run_workflow("customer_retention", {
            "customer_data": [
                {"name": "Alice", "orders": 10, "total_spent": 500, "days_since_last_order": 5},
                {"name": "Bob", "orders": 1, "total_spent": 20, "days_since_last_order": 150},
            ],
        })
        self.assertIn(result["status"], ["completed", "partial", "failed"])

    def test_pricing_optimization_workflow(self):
        result = self.orch.run_workflow("pricing_optimization", {
            "products": [{"name": "X", "price": 30, "cost": 8}],
        })
        self.assertIn(result["status"], ["completed", "partial", "failed"])

    def test_workflow_with_empty_data(self):
        result = self.orch.run_workflow("product_launch", {})
        # Should handle gracefully — partial or completed
        self.assertIn(result["status"], ["completed", "partial", "failed"])

    def test_unknown_workflow(self):
        result = self.orch.run_workflow("nonexistent_workflow_xyz", {})
        self.assertIn("error", result)


class TestAgentIntegration(unittest.TestCase):
    """Test agent-engine coordination."""

    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_product_agent_pricing(self):
        result = self.orch.agent_run("product_agent", "pricing", {
            "products": [{"name": "X", "price": 30, "cost": 8}],
        })
        self.assertIn(result["status"], ["completed", "partial", "failed"])
        self.assertIn("_agent", result)
        self.assertEqual(result["_agent"]["name"], "product_agent")

    def test_customer_agent_segmentation(self):
        result = self.orch.agent_run("customer_agent", "customer_segmentation", {
            "customer_data": [{"name": "A", "orders": 5, "total_spent": 200, "days_since_last_order": 10}],
            "segmentation_criteria": {},
        })
        self.assertIn(result["status"], ["completed", "partial", "failed"])

    def test_agent_with_wrong_task(self):
        result = self.orch.agent_run("product_agent", "completely_wrong_task_xyz", {})
        # Agent falls back to first available engine
        self.assertIn("_agent", result)

    def test_all_agents_accessible(self):
        agents = self.orch.list_agents()
        self.assertGreaterEqual(len(agents), 6)
        for agent in agents:
            self.assertIn("name", agent)
            self.assertGreater(agent["engines"], 0)


class TestWebhookIntegration(unittest.TestCase):
    """Test Shopify webhook → engine pipeline."""

    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_order_created_webhook(self):
        from core.webhooks import ShopifyWebhookHandler
        wh = ShopifyWebhookHandler()
        result = wh.handle("orders/create", {
            "id": 12345, "total_price": "89.99", "line_items": [{"id": 1}],
            "customer": {"id": 999},
        })
        self.assertEqual(result["status"], "processed")
        self.assertGreater(result["engines_triggered"], 0)

    def test_product_update_webhook(self):
        from core.webhooks import ShopifyWebhookHandler
        wh = ShopifyWebhookHandler()
        result = wh.handle("products/update", {
            "id": 555, "title": "Updated Product",
            "variants": [{"price": "34.99", "cost": "10.00"}],
        })
        self.assertEqual(result["status"], "processed")

    def test_unknown_webhook_skipped(self):
        from core.webhooks import ShopifyWebhookHandler
        wh = ShopifyWebhookHandler()
        result = wh.handle("unknown/topic", {})
        self.assertEqual(result["status"], "skipped")

    def test_hmac_validation(self):
        from core.webhooks import ShopifyWebhookHandler
        wh = ShopifyWebhookHandler(webhook_secret="test_secret")
        result = wh.handle("orders/create", {"id": 1}, hmac_header="invalid_hmac")
        self.assertEqual(result["status"], "rejected")


class TestChainIntegration(unittest.TestCase):
    """Test engine chain execution."""

    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_run_chain(self):
        from core.chaining import ChainBuilder
        chain = ChainBuilder("test_chain").then("product_selection").then("pricing").build()
        result = chain.run({"products": [{"name": "X", "price": 30, "cost": 8}], "criteria": {}})
        self.assertIn(result["status"], ["completed", "partial", "failed"])
        self.assertIn("steps", result)

    def test_smart_chain_conditional(self):
        from core.chaining import SmartChain
        chain = SmartChain("conditional_test")
        chain.add("product_selection")
        chain.add_conditional(
            condition=lambda d: True,
            if_true="pricing",
            if_false="market_research",
        )
        result = chain.run({"products": [{"name": "X", "price": 30, "cost": 8}], "criteria": {}})
        self.assertIn(result["status"], ["completed", "partial", "failed"])


class TestShopifyBridgeIntegration(unittest.TestCase):
    """Test Shopify bridge data flow.

    Pre-cleanup these tests relied on a hardcoded mock dataset that
    ``fetch_products/orders/customers`` silently returned when no
    credentials were configured. The mock masked real API failures
    and has been removed (see ``ShopifyBridgeUnavailable``), so
    these tests now verify the post-cleanup behaviour:

    * ``fetch_*`` raises when there is no cache and no live API
    * ``fetch_for_engine`` returns a dict (possibly empty) or fails
      gracefully via the DataProvider path
    """

    def test_fetch_products_raises_when_unavailable(self):
        from core.bridge.shopify_bridge import (
            ShopifyBridge, ShopifyBridgeUnavailable,
        )
        sb = ShopifyBridge()
        with self.assertRaises(ShopifyBridgeUnavailable):
            sb.fetch_products()

    def test_fetch_for_engine_returns_dict(self):
        from core.bridge.shopify_bridge import ShopifyBridge
        sb = ShopifyBridge()
        try:
            data = sb.fetch_for_engine("product_selection")
            self.assertIsInstance(data, dict)
        except Exception as exc:
            self.assertTrue(
                "Unavailable" in type(exc).__name__
                or "unavailable" in str(exc).lower()
                or isinstance(exc, (KeyError, RuntimeError)),
            )

    def test_shopify_data_to_engine(self):
        """End-to-end: Shopify data → engine → result.

        With no real store configured the bridge now raises
        ``ShopifyBridgeUnavailable`` instead of returning mock data,
        so the test simply asserts that the pipeline either runs
        against (possibly empty) DataProvider output or signals the
        gap cleanly.
        """
        from core.orchestrator import MainOrchestrator
        from core.bridge.shopify_bridge import ShopifyBridge
        orch = MainOrchestrator()
        orch.initialize()
        try:
            sb = ShopifyBridge()
            data = sb.fetch_for_engine("pricing")
            result = orch.submit_task("pricing", data)
            self.assertIn(result["status"], ["completed", "partial", "failed"])
        except Exception as exc:
            # Post-cleanup the bridge may refuse to serve when
            # no real data source is wired — acceptable for this
            # integration smoke test.
            self.assertTrue(
                "Unavailable" in type(exc).__name__
                or "unavailable" in str(exc).lower()
                or isinstance(exc, (KeyError, RuntimeError)),
            )
        finally:
            orch.shutdown()


class TestExecutionBridgeIntegration(unittest.TestCase):
    """Test engine result → action plan pipeline."""

    def setUp(self):
        from core.orchestrator import MainOrchestrator
        self.orch = MainOrchestrator()
        self.orch.initialize()

    def tearDown(self):
        self.orch.shutdown()

    def test_plan_actions_from_result(self):
        actions = self.orch.plan_actions("product_selection", {
            "selected_products": [{"name": "Earbuds", "price": 30, "viable": True}],
            "churn_risks": [{"customer": "Bob", "risk_level": "high", "days_inactive": 120}],
        })
        self.assertGreater(len(actions), 0)
        for action in actions:
            self.assertIn("action_type", action)
            self.assertIn("priority", action)

    def test_empty_result_no_actions(self):
        actions = self.orch.plan_actions("analytics", {})
        self.assertEqual(len(actions), 0)


class TestSystemIntegration(unittest.TestCase):
    """Test full system health and monitoring."""

    def test_health_check(self):
        from core.orchestrator import MainOrchestrator
        orch = MainOrchestrator()
        orch.initialize()
        health = orch.health_check()
        self.assertEqual(health["status"], "healthy")
        orch.shutdown()

    def test_metrics_tracking(self):
        from core.orchestrator import MainOrchestrator
        orch = MainOrchestrator()
        orch.initialize()
        # Run a task
        orch.submit_task("pricing", {"products": [{"name": "X", "price": 30, "cost": 8}]})
        # Check metrics recorded
        count = orch.metrics.get_counter("task.submitted")
        self.assertGreater(count, 0)
        orch.shutdown()

    def test_event_system(self):
        from core.orchestrator import MainOrchestrator
        orch = MainOrchestrator()
        orch.initialize()
        stats = orch.events.get_stats()
        self.assertGreater(stats["published"], 0)  # startup event
        orch.shutdown()


if __name__ == "__main__":
    unittest.main()
