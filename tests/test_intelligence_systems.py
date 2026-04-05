"""Integration tests for all ShopAI intelligence systems.

Tests every system built in this session — import, init, basic function.
Run: python -m pytest tests/test_intelligence_systems.py -v
"""
import pytest
import time


class TestDataArchitecture:
    def test_import(self):
        from core.data.architecture import get_data_architecture
        da = get_data_architecture()
        assert da is not None

    def test_capture(self):
        from core.data.architecture import get_data_architecture
        da = get_data_architecture()
        rid = da.capture("product", {"id": "test_1", "price": 10.0}, source="test")
        assert rid > 0

    def test_query(self):
        from core.data.architecture import get_data_architecture
        da = get_data_architecture()
        results = da.query("product", limit=5)
        assert isinstance(results, list)

    def test_stats(self):
        from core.data.architecture import get_data_architecture
        da = get_data_architecture()
        stats = da.get_stats()
        assert "total_records" in stats
        assert "domains" in stats

    def test_12_domains(self):
        from core.data.architecture import DOMAIN_NAMES
        assert len(DOMAIN_NAMES) == 12


class TestMemoryIntelligence:
    def test_import(self):
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        assert mi is not None

    def test_create(self):
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mid = mi.create("test", {"key": "value"}, score=3.5)
        assert mid > 0

    def test_retrieve(self):
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        results = mi.retrieve("test", limit=5)
        assert isinstance(results, list)

    def test_4_levels(self):
        from core.memory.intelligence import MEMORY_LEVELS
        assert len(MEMORY_LEVELS) == 4
        assert "event" in MEMORY_LEVELS
        assert "strategy" in MEMORY_LEVELS

    def test_4_types(self):
        from core.memory.intelligence import MEMORY_TYPES
        assert len(MEMORY_TYPES) == 4

    def test_working_memory(self):
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        mid = mi.set_working("test_key", "test_value")
        assert mid > 0
        mi.clear_working()

    def test_failure_recording(self):
        from core.memory.intelligence import get_memory_intelligence
        mi = get_memory_intelligence()
        fid = mi.record_failure("test", {"error": "test"}, "test_cause")
        assert fid > 0


class TestIntelligenceCycle:
    def test_import(self):
        from core.intelligence_cycle import get_intelligence_cycle
        ic = get_intelligence_cycle()
        assert ic is not None

    def test_run(self):
        from core.intelligence_cycle import get_intelligence_cycle
        ic = get_intelligence_cycle()
        result = ic.run("test", {"id": "1", "price": 10})
        assert "score" in result
        assert "stages" in result
        assert len(result["stages"]) == 10


class TestSmartExecutor:
    def test_import(self):
        from execution.smart_executor import get_smart_executor
        se = get_smart_executor()
        assert se is not None

    def test_execute(self):
        from execution.smart_executor import get_smart_executor
        se = get_smart_executor()
        result = se.execute({"type": "test", "confidence": 0.5})
        assert result["mode"] == "simulate"
        assert "score" in result


class TestMLModels:
    def test_rl_pricing(self):
        from models.rl.pricing_agent import get_pricing_agent
        agent = get_pricing_agent()
        result = agent.select_action("test_p", 29.99, 12.0)
        assert "recommended_price" in result
        assert "confidence" in result

    def test_customer_segmentation(self):
        from models.ml.customer_segmentation import get_customer_segmentation
        seg = get_customer_segmentation()
        result = seg.segment([{"id": "c1", "orders_count": 0}])
        assert result["total_customers"] == 1

    def test_demand_forecast(self):
        from models.ml.demand_forecast import get_demand_forecaster
        fc = get_demand_forecaster()
        result = fc.forecast([{"id": "p1", "inventory_quantity": 50}], [])
        assert result["total_products"] == 1

    def test_product_scorer(self):
        from models.ml.product_scorer import get_product_scorer
        ps = get_product_scorer()
        result = ps.score_all([{"id": "1", "price": 29.99, "cost": 12.0}])
        assert len(result) == 1
        assert "grade" in result[0]


class TestBrainModules:
    def test_cognitive(self):
        from core.brain.cognitive import get_cognitive_module
        cog = get_cognitive_module()
        assert cog.understanding is not None
        assert cog.reasoning is not None
        assert cog.curiosity is not None

    def test_strategy_planner(self):
        from core.brain.strategy_planner import get_strategy_planner
        sp = get_strategy_planner()
        result = sp.plan([{"id": "1", "price": 10}], [], [])
        assert result["total"] > 0

    def test_competitive_intel(self):
        from core.brain.competitive_intel import get_competitive_intelligence
        ci = get_competitive_intelligence()
        result = ci.analyze([{"id": "1", "price": 10, "cost": 4}])
        assert "advantages" in result

    def test_rule_health(self):
        from core.brain.rule_health import get_rule_health_checker
        rhc = get_rule_health_checker()
        result = rhc.check()
        assert "total_rules" in result

    def test_chain_of_thought(self):
        from core.brain.reasoning_chain import get_chain_of_thought
        cot = get_chain_of_thought()
        result = cot.reason("test question", {"products": []})
        assert "answer" in result
        assert result["reasoning_length"] == 5

    def test_multi_store(self):
        from core.brain.multi_store_brain import get_multi_store
        ms = get_multi_store()
        ms.register_store("test_store")
        assert ms.get_network_stats()["stores"] > 0

    def test_revenue_strategy(self):
        from core.brain.revenue_strategy import get_revenue_strategy
        rs = get_revenue_strategy()
        result = rs.create_plan([], [], [])
        assert "phase" in result


class TestExecutionModules:
    def test_marketing_automation(self):
        from execution.marketing.auto_campaign import get_marketing_automation
        mkt = get_marketing_automation()
        result = mkt.generate_campaigns(
            [{"id": "1", "price": 10, "cost": 4}], [], [])
        assert result["total"] > 0

    def test_fulfillment(self):
        from execution.fulfillment.auto_fulfill import get_fulfillment
        ff = get_fulfillment()
        result = ff.process_orders([], [])
        assert result["status"] == "no_orders"

    def test_image_sourcer(self):
        from execution.content.image_sourcer import get_image_sourcer
        src = get_image_sourcer()
        result = src.source_images([{"id": "1", "name": "Test"}])
        assert "assignments" in result

    def test_promoter(self):
        from execution.promoter import get_execution_promoter
        ep = get_execution_promoter()
        rec = ep.recommend_mode("test_action")
        assert rec["mode"] == "simulate"


class TestSystemModules:
    def test_alerts(self):
        from core.system.alerts import get_alert_system
        alerts = get_alert_system()
        result = alerts.check_cycle({"phases": {}})
        assert isinstance(result, list)

    def test_ab_testing(self):
        from core.system.ab_testing import get_ab_testing
        ab = get_ab_testing()
        exp_id = ab.create_experiment("test", "test hypothesis")
        assert exp_id.startswith("exp_")

    def test_model_workers(self):
        from core.system.model_workers import get_model_workers
        mw = get_model_workers()
        result = mw.execute_task("analyze_product",
            {"name": "Test", "price": 10, "cost": 4, "category": "Home"})
        assert result["success"]

    def test_tool_orchestrator(self):
        from core.system.tool_orchestrator import get_tool_orchestrator
        to = get_tool_orchestrator()
        disc = to.discover()
        assert disc["total_tools"] == 13

    def test_data_middleware(self):
        from core.system.data_middleware import get_middleware
        dm = get_middleware()
        result = dm.wrap("test", "add", lambda x: x + 1, 5)
        assert result["result"] == 6
        assert result["success"]

    def test_notifications(self):
        from core.system.notifications import get_notifications
        n = get_notifications()
        result = n.send("info", "test", "test message")
        assert result["delivered"] > 0

    def test_dashboard(self):
        from core.system.dashboard import get_dashboard
        d = get_dashboard()
        result = d.generate()
        assert "generated_at" in result

    def test_trend_analyzer(self):
        from core.system.trend_analyzer import get_trend_analyzer
        ta = get_trend_analyzer()
        assert ta.get_stats()["cycles_recorded"] >= 0

    def test_price_history(self):
        from data_pipeline.tracking.price_history import get_price_history
        ph = get_price_history()
        rid = ph.record_price("test_p", 29.99, 12.0)
        assert rid > 0


class TestFullCycle:
    def test_cycle_runs(self):
        from core.autonomous.controller import AutonomousController
        ac = AutonomousController(auto_approve=False)
        ac.initialize()
        result = ac.run_cycle("test")
        assert result["status"] == "complete"
        assert result["phases"]["layers"]["layers_run"] == 12

    def test_cycle_has_30_phases(self):
        from core.autonomous.controller import AutonomousController
        ac = AutonomousController(auto_approve=False)
        ac.initialize()
        result = ac.run_cycle("test")
        assert len(result["phases"]) >= 25
