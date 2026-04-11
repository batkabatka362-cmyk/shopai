"""Test suite for agents and tools — import, contract, execution.

Tests:
  - All 7 agents import and implement BaseAgent contract (plan/execute/evaluate)
  - Agent planners have GOAL_ENGINE_MAP
  - Agent planning produces valid engine lists
  - Tool base classes import
  - ToolRegistry singleton works
  - All 13 adapters import and have capabilities()
  - ToolOrchestrator instantiates
"""
import unittest
import importlib


# ── Agent modules: (module_path, class_name) ──
AGENT_MODULES = [
    ("agents.research.agent", "ResearchAgent"),
    ("agents.product.agent", "ProductAgent"),
    ("agents.finance.agent", "FinanceAgent"),
    ("agents.customer.agent", "CustomerAgent"),
    ("agents.marketing.agent", "MarketingAgent"),
    ("agents.content.agent", "ContentAgent"),
    ("agents.operations.agent", "OperationsAgent"),
]

# ── Agent planner modules that should have GOAL_ENGINE_MAP ──
PLANNER_MODULES = [
    "agents.research.planner",
    "agents.product.planner",
    "agents.finance.planner",
]

# ── Tool adapter classes (from tools/adapters/__init__.py) ──
ADAPTER_CLASSES = [
    ("tools.adapters.analytics", "AnalyticsAdapter"),
    ("tools.adapters.browser_automation", "BrowserAutomationAdapter"),
    ("tools.adapters.cloud_ai", "CloudAIAdapter"),
    ("tools.adapters.crm", "CRMAdapter"),
    ("tools.adapters.email_service", "EmailServiceAdapter"),
    ("tools.adapters.google_ads", "GoogleAdsAdapter"),
    ("tools.adapters.image_generation", "ImageGenerationAdapter"),
    ("tools.adapters.meta_ads", "MetaAdsAdapter"),
    ("tools.adapters.payment", "PaymentAdapter"),
    ("tools.adapters.shopify", "ShopifyAdapter"),
    ("tools.adapters.sms", "SMSAdapter"),
    ("tools.adapters.tiktok_ads", "TikTokAdsAdapter"),
    ("tools.adapters.workflow_automation", "WorkflowAutomationAdapter"),
]


# ======================================================================
# Agent Import Tests
# ======================================================================


class TestAgentImport(unittest.TestCase):
    """Verify all 7 agents import and satisfy BaseAgent contract."""

    def test_all_agents_import(self):
        """All 7 agent modules should import and provide the expected class."""
        errors = []
        for module_path, class_name in AGENT_MODULES:
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name, None)
                self.assertIsNotNone(cls, f"{class_name} not found in {module_path}")
            except Exception as exc:
                errors.append(f"{module_path}.{class_name}: {exc}")
        self.assertEqual(errors, [], f"Import failures: {errors}")

    def test_all_agents_have_plan_execute_evaluate(self):
        """Every agent must implement plan(), execute(), evaluate() from BaseAgent."""
        for module_path, class_name in AGENT_MODULES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()

            for method_name in ("plan", "execute", "evaluate"):
                self.assertTrue(
                    hasattr(instance, method_name),
                    f"{class_name} missing {method_name}()",
                )
                self.assertTrue(
                    callable(getattr(instance, method_name)),
                    f"{class_name}.{method_name} not callable",
                )

    def test_all_agents_have_run(self):
        """Every agent should have a run() method (from BaseAgent)."""
        for module_path, class_name in AGENT_MODULES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()
            self.assertTrue(
                hasattr(instance, "run"),
                f"{class_name} missing run()",
            )
            self.assertTrue(
                callable(instance.run),
                f"{class_name}.run not callable",
            )

    def test_all_agents_have_name(self):
        """Every agent instance should have a non-empty name attribute."""
        for module_path, class_name in AGENT_MODULES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()
            self.assertTrue(hasattr(instance, "name"), f"{class_name} missing name")
            self.assertIsInstance(instance.name, str)
            self.assertGreater(len(instance.name), 0, f"{class_name}.name is empty")

    def test_agent_planner_has_goal_map(self):
        """Planner modules should define GOAL_ENGINE_MAP."""
        for planner_path in PLANNER_MODULES:
            mod = importlib.import_module(planner_path)
            self.assertTrue(
                hasattr(mod, "GOAL_ENGINE_MAP"),
                f"{planner_path} missing GOAL_ENGINE_MAP",
            )
            goal_map = getattr(mod, "GOAL_ENGINE_MAP")
            self.assertIsInstance(goal_map, dict, f"{planner_path} GOAL_ENGINE_MAP is not a dict")
            self.assertGreater(
                len(goal_map), 0,
                f"{planner_path} GOAL_ENGINE_MAP is empty",
            )
            # Each entry should map to a list of engine names
            for goal_key, engines in goal_map.items():
                self.assertIsInstance(
                    engines, list,
                    f"{planner_path} GOAL_ENGINE_MAP[{goal_key!r}] is not a list",
                )
                self.assertGreater(len(engines), 0)

    def test_agent_inherits_base_agent(self):
        """All agents should inherit from BaseAgent."""
        from agents.base import BaseAgent
        for module_path, class_name in AGENT_MODULES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            self.assertTrue(
                issubclass(cls, BaseAgent),
                f"{class_name} does not inherit from BaseAgent",
            )

    def test_agent_count(self):
        """We should have exactly 7 agents defined."""
        self.assertEqual(len(AGENT_MODULES), 7)


# ======================================================================
# Agent Execution Tests
# ======================================================================


class TestAgentExecution(unittest.TestCase):
    """Test that agents can plan for specific goals."""

    def test_research_agent_plans(self):
        """ResearchAgent should produce a plan for 'find trending products'."""
        from agents.research.planner import create_plan
        plan = create_plan(
            goal="find trending products",
            context={"category": "electronics"},
            constraints={},
        )
        self.assertIsInstance(plan, dict)
        self.assertIn("engines", plan)
        self.assertIsInstance(plan["engines"], list)
        self.assertGreater(len(plan["engines"]), 0)
        self.assertIn("strategy", plan)

        # Verify engine steps have required fields
        for step in plan["engines"]:
            self.assertIn("name", step)
            self.assertIn("input", step)

    def test_product_agent_plans(self):
        """ProductAgent planner should produce a plan for 'launch_product'."""
        from agents.product.planner import create_plan
        plan = create_plan(
            goal="launch_product",
            context={
                "products": [{"id": "p1", "title": "Test", "price": 25.0}],
                "category": "gadgets",
            },
            constraints={},
        )
        self.assertIsInstance(plan, dict)
        self.assertIn("engines", plan)
        self.assertIsInstance(plan["engines"], list)
        self.assertGreater(len(plan["engines"]), 0)

        # launch_product should include multiple pipeline steps
        engine_names = [e["name"] for e in plan["engines"]]
        self.assertGreater(len(engine_names), 1, "launch_product should use multiple engines")

    def test_finance_agent_plans(self):
        """FinanceAgent planner should produce a plan for 'optimize_profit'."""
        from agents.finance.planner import create_plan
        plan = create_plan(
            goal="optimize_profit",
            context={
                "orders": [{"id": "o1", "total": 100}],
                "products": [{"id": "p1", "price": 25.0, "cost": 10.0}],
            },
            constraints={},
        )
        self.assertIsInstance(plan, dict)
        self.assertIn("engines", plan)
        self.assertIsInstance(plan["engines"], list)
        self.assertGreater(len(plan["engines"]), 0)

        # optimize_profit should include financial and profit-related engines
        engine_names = [e["name"] for e in plan["engines"]]
        self.assertIn("financial", engine_names)

    def test_research_agent_default_plan(self):
        """Unknown goal should fall back to default engines."""
        from agents.research.planner import create_plan
        plan = create_plan(
            goal="something_unusual",
            context={"category": "misc"},
            constraints={},
        )
        self.assertIn("engines", plan)
        self.assertGreater(len(plan["engines"]), 0)

    def test_plan_includes_estimated_steps(self):
        """Plans should include estimated_steps matching engines count."""
        from agents.research.planner import create_plan
        plan = create_plan(
            goal="full_research",
            context={"category": "fashion"},
            constraints={},
        )
        self.assertIn("estimated_steps", plan)
        self.assertEqual(plan["estimated_steps"], len(plan["engines"]))


# ======================================================================
# Tools Import Tests
# ======================================================================


class TestToolsImport(unittest.TestCase):
    """Verify tool base classes, registry, and adapters import correctly."""

    def test_base_imports(self):
        """BaseToolAdapter, ToolResult, and ToolMetadata should import."""
        from tools.base import BaseToolAdapter, ToolResult, ToolMetadata
        self.assertIsNotNone(BaseToolAdapter)
        self.assertIsNotNone(ToolResult)
        self.assertIsNotNone(ToolMetadata)

    def test_base_tool_result_defaults(self):
        """ToolResult should have sensible defaults."""
        from tools.base import ToolResult
        result = ToolResult(success=True)
        self.assertTrue(result.success)
        self.assertEqual(result.data, {})
        self.assertIsNone(result.error)
        self.assertIsNone(result.metadata)

    def test_base_tool_metadata_defaults(self):
        """ToolMetadata should have zero/empty defaults."""
        from tools.base import ToolMetadata
        meta = ToolMetadata()
        self.assertEqual(meta.duration_ms, 0.0)
        self.assertEqual(meta.attempt_count, 1)
        self.assertFalse(meta.rate_limited)
        self.assertEqual(meta.cost_usd, 0.0)
        self.assertEqual(meta.tool_name, "")

    def test_health_status_imports(self):
        """HealthStatus and RateConfig should import."""
        from tools.base import HealthStatus, RateConfig
        health = HealthStatus(healthy=True)
        self.assertTrue(health.healthy)
        rate = RateConfig()
        self.assertGreater(rate.requests_per_second, 0)

    def test_registry_singleton(self):
        """ToolRegistry.instance() should return the same object each time."""
        from tools.registry import ToolRegistry
        r1 = ToolRegistry.instance()
        r2 = ToolRegistry.instance()
        self.assertIs(r1, r2)

    def test_registry_reset_singleton(self):
        """reset_singleton should allow a new instance to be created."""
        from tools.registry import ToolRegistry
        r1 = ToolRegistry.instance()
        ToolRegistry.reset_singleton()
        r2 = ToolRegistry.instance()
        self.assertIsNot(r1, r2)
        # Clean up: reset so other tests get a fresh registry
        ToolRegistry.reset_singleton()

    def test_registry_register_and_get(self):
        """Registry should store and retrieve adapters by name."""
        from tools.registry import ToolRegistry
        from tools.adapters.analytics import AnalyticsAdapter
        registry = ToolRegistry()  # fresh instance, not singleton
        adapter = AnalyticsAdapter()
        registry.register(adapter)
        retrieved = registry.get(adapter.tool_name)
        self.assertIs(retrieved, adapter)

    def test_registry_get_unknown_returns_none(self):
        """Getting a non-registered tool should return None."""
        from tools.registry import ToolRegistry
        registry = ToolRegistry()
        self.assertIsNone(registry.get("nonexistent_tool_xyz_99"))

    def test_all_adapters_import(self):
        """All 13 tool adapters should import without error."""
        errors = []
        for module_path, class_name in ADAPTER_CLASSES:
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name, None)
                self.assertIsNotNone(cls, f"{class_name} not found in {module_path}")
            except Exception as exc:
                errors.append(f"{module_path}.{class_name}: {exc}")
        self.assertEqual(errors, [], f"Adapter import failures: {errors}")

    def test_adapter_count(self):
        """We should have exactly 13 adapters."""
        self.assertEqual(len(ADAPTER_CLASSES), 13)

    def test_adapter_has_capabilities(self):
        """Every adapter instance must have a callable capabilities() method."""
        for module_path, class_name in ADAPTER_CLASSES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()
            self.assertTrue(
                hasattr(instance, "capabilities"),
                f"{class_name} missing capabilities()",
            )
            self.assertTrue(
                callable(instance.capabilities),
                f"{class_name}.capabilities not callable",
            )
            caps = instance.capabilities()
            self.assertIsInstance(
                caps, list,
                f"{class_name}.capabilities() did not return a list",
            )
            self.assertGreater(
                len(caps), 0,
                f"{class_name}.capabilities() returned empty list",
            )

    def test_adapter_has_tool_name(self):
        """Every adapter should have a non-empty tool_name."""
        for module_path, class_name in ADAPTER_CLASSES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()
            self.assertTrue(
                hasattr(instance, "tool_name"),
                f"{class_name} missing tool_name",
            )
            self.assertIsInstance(instance.tool_name, str)
            self.assertGreater(
                len(instance.tool_name), 0,
                f"{class_name}.tool_name is empty",
            )

    def test_adapter_has_execute_and_health_check(self):
        """Every adapter should implement execute() and health_check()."""
        for module_path, class_name in ADAPTER_CLASSES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            instance = cls()
            self.assertTrue(
                callable(getattr(instance, "execute", None)),
                f"{class_name} missing execute()",
            )
            self.assertTrue(
                callable(getattr(instance, "health_check", None)),
                f"{class_name} missing health_check()",
            )

    def test_adapter_inherits_base(self):
        """All adapters should inherit from BaseToolAdapter."""
        from tools.base import BaseToolAdapter
        for module_path, class_name in ADAPTER_CLASSES:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            self.assertTrue(
                issubclass(cls, BaseToolAdapter),
                f"{class_name} does not inherit from BaseToolAdapter",
            )

    def test_orchestrator_creates(self):
        """ToolOrchestrator should instantiate with a ToolRegistry."""
        from tools.orchestrator import ToolOrchestrator
        from tools.registry import ToolRegistry
        registry = ToolRegistry()
        orchestrator = ToolOrchestrator(registry=registry)
        self.assertIsNotNone(orchestrator)

    def test_orchestrator_has_registry_ref(self):
        """ToolOrchestrator should hold a reference to the registry."""
        from tools.orchestrator import ToolOrchestrator
        from tools.registry import ToolRegistry
        registry = ToolRegistry()
        orchestrator = ToolOrchestrator(registry=registry)
        self.assertIs(orchestrator._registry, registry)


if __name__ == "__main__":
    unittest.main()
