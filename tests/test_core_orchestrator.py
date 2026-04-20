"""Tests for CoreOrchestrator — the central brain + all coordination components.

Pre-cleanup these tests implicitly relied on ``ShopifyBridge``
silently substituting a hardcoded mock dataset (5 fake products,
5 fake orders, 4 fake customers) whenever no real Shopify store
was wired up. The mock fallback was removed as part of the stub
cleanup pass — the bridge now raises ``ShopifyBridgeUnavailable``
in that situation, which would leave every cycle in this test
file with empty data and break the assertions that expect
positive product / revenue counts.

The autouse ``_seed_shopify_bridge`` fixture below restores the
old behaviour explicitly: it patches the bridge to return a
controlled test dataset only inside this file. Any test that
previously depended on the silent mock continues to pass; any
test that wants to assert the *new* honest "no data" behaviour
should opt out of the fixture or use ``ShopifyBridgeUnavailable``
directly (see ``tests/test_stub_cleanup.py``).
"""
import time
import pytest
from core.core_orchestrator import CoreOrchestrator
from core.orchestrator.store_snapshot import StoreSnapshot
from core.orchestrator.priority_engine import PriorityEngine
from core.orchestrator.action_coordinator import ActionCoordinator
from core.orchestrator.cycle_journal import CycleJournal


_TEST_PRODUCTS = [
    {"id": "1", "name": "Test Earbuds", "price": 49.99, "cost": 15,
     "category": "electronics", "inventory_quantity": 150},
    {"id": "2", "name": "Test Mat", "price": 39.99, "cost": 12,
     "category": "fitness", "inventory_quantity": 80},
    {"id": "3", "name": "Test Lamp", "price": 34.99, "cost": 18,
     "category": "home", "inventory_quantity": 45},
]
_TEST_ORDERS = [
    {"id": "1001", "total": 89.98, "subtotal": 84.98, "status": "paid",
     "items": 2, "customer_id": "c1"},
    {"id": "1002", "total": 49.99, "subtotal": 49.99, "status": "paid",
     "items": 1, "customer_id": "c2"},
    {"id": "1003", "total": 124.97, "subtotal": 119.97, "status": "paid",
     "items": 3, "customer_id": "c1"},
]
_TEST_CUSTOMERS = [
    {"id": "c1", "name": "Test Alice", "email": "alice@test.local",
     "orders": 8, "total_spent": 650},
    {"id": "c2", "name": "Test Bob", "email": "bob@test.local",
     "orders": 1, "total_spent": 49.99},
]


@pytest.fixture(autouse=True)
def _seed_shopify_bridge(monkeypatch):
    """Patch ``ShopifyBridge`` and ``DataProvider`` so the cycle has
    deterministic test data without depending on the deleted silent
    ``_mock_*`` fallback. Replaces the pre-cleanup implicit mock."""
    from core.bridge.shopify_bridge import ShopifyBridge
    from data_pipeline.store.data_provider import DataProvider

    monkeypatch.setattr(
        ShopifyBridge, "fetch_products",
        lambda self, limit=50: list(_TEST_PRODUCTS)[:limit],
    )
    monkeypatch.setattr(
        ShopifyBridge, "fetch_orders",
        lambda self, days_back=30, limit=100: list(_TEST_ORDERS)[:limit],
    )
    monkeypatch.setattr(
        ShopifyBridge, "fetch_customers",
        lambda self, limit=100: list(_TEST_CUSTOMERS)[:limit],
    )
    monkeypatch.setattr(
        DataProvider, "get_products",
        lambda self, store_id="", **kw: list(_TEST_PRODUCTS),
    )
    monkeypatch.setattr(
        DataProvider, "get_orders",
        lambda self, store_id="", **kw: list(_TEST_ORDERS),
    )
    monkeypatch.setattr(
        DataProvider, "get_customers",
        lambda self, store_id="", **kw: list(_TEST_CUSTOMERS),
    )
    yield


# ── CoreOrchestrator Init ──

class TestCoreOrchestratorInit:
    def test_all_modules_load(self):
        c = CoreOrchestrator()
        status = c.status()
        assert status["initialized"] is True
        assert status["modules_count"] >= 20  # At least 20 modules loaded

    def test_expected_modules_present(self):
        c = CoreOrchestrator()
        modules = c.status()["modules_loaded"]
        expected = [
            "shopify_bridge", "intelligence_loop", "financial_brain",
            "campaign_optimizer", "ads_intelligence", "strategy_optimizer",
            "competitive_loop", "kpi_tracker", "revenue_tracker",
            "system_health", "event_reactor", "scheduler",
        ]
        for m in expected:
            assert m in modules, f"Module {m} not loaded"

    def test_get_module(self):
        c = CoreOrchestrator()
        assert c.get_module("financial_brain") is not None
        assert c.get_module("nonexistent") is None

    def test_coordination_components_initialized(self):
        c = CoreOrchestrator()
        assert c.snapshot is not None
        assert c.priority_engine is not None
        assert c.action_coordinator is not None
        assert c.journal is not None


# ── Run Cycle ──

class TestRunCycle:
    def test_cycle_completes(self):
        c = CoreOrchestrator()
        result = c.run_cycle(goal="maximize_profit")
        assert "cycle_id" in result
        assert result["cycle_id"].startswith("cycle_")
        assert result["elapsed_seconds"] > 0
        assert result["goal"] == "maximize_profit"

    def test_all_phases_present(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        phases = result["phases"]
        for p in ["data", "financial", "campaigns", "competitive",
                   "intelligence", "strategy", "events", "health"]:
            assert p in phases, f"Phase {p} missing"

    def test_data_phase_fetches(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        data = result["phases"]["data"]
        assert data["products"] > 0
        assert data["orders"] > 0
        assert data["customers"] > 0

    def test_financial_phase_computes_pnl(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        fin = result["phases"]["financial"]
        assert "pnl" in fin
        assert fin["pnl"]["gross_revenue"] > 0

    def test_intelligence_phase_makes_decision(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        intel = result["phases"]["intelligence"]
        assert intel.get("stages_completed") == 7
        assert "decision" in intel
        assert intel["decision"]["confidence"] in ("low", "medium", "high")

    def test_strategy_phase_has_autopilot(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        strat = result["phases"]["strategy"]
        assert "autopilot" in strat
        assert "should_switch" in strat["autopilot"]

    def test_health_phase_has_grade(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        health = result["phases"]["health"]
        assert health["overall_grade"] in ("A", "B", "C", "D", "F")

    def test_summary_has_key_metrics(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        summary = result["summary"]
        for key in ["decision", "confidence", "confidence_score", "data_quality", "modules_active"]:
            assert key in summary
        assert summary["modules_active"] >= 20

    def test_different_goals(self):
        c = CoreOrchestrator()
        for goal in ["maximize_profit", "grow_customers", "increase_aov"]:
            result = c.run_cycle(goal=goal)
            assert result["goal"] == goal

    def test_priorities_computed(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        assert "priorities" in result
        assert len(result["priorities"]) > 0
        for p in result["priorities"]:
            assert "domain" in p
            assert "urgency" in p
            assert "score" in p


# ── StoreSnapshot ──

class TestStoreSnapshot:
    def test_update_financial(self):
        snap = StoreSnapshot()
        snap.update_financial({
            "pnl": {"gross_revenue": 1000, "net_profit": 200, "net_margin": 20, "gross_margin": 40,
                     "total_costs": 800, "order_count": 50, "aov": 20, "status": "profitable"},
            "margin_alerts": [{"severity": "critical"}, {"severity": "high"}],
            "health": {"score": 75, "grade": "B"},
        })
        assert snap.financial["gross_revenue"] == 1000
        assert snap.financial["critical_alerts"] == 1
        assert snap.financial["health_grade"] == "B"

    def test_update_inventory(self):
        snap = StoreSnapshot()
        products = [
            {"inventory_quantity": 100},
            {"inventory_quantity": 5},
            {"inventory_quantity": 0},
        ]
        snap.update_inventory(products)
        assert snap.inventory["total_products"] == 3
        assert snap.inventory["low_stock_count"] == 2
        assert snap.inventory["out_of_stock_count"] == 1
        assert snap.inventory["stockout_risk"] is True

    def test_update_customers(self):
        snap = StoreSnapshot()
        customers = [{"id": 1}, {"id": 2}, {"id": 3}]
        orders = [{"customer": {"id": 1}}]
        snap.update_customers(customers, orders)
        assert snap.customers["total"] == 3
        assert snap.customers["active_recent"] == 1
        assert snap.customers["churn_risk_pct"] > 0

    def test_get_situation(self):
        snap = StoreSnapshot()
        snap.update_financial({"pnl": {"gross_revenue": 500}})
        snap.finalize("test_cycle")
        situation = snap.get_situation()
        assert situation["cycle_id"] == "test_cycle"
        assert situation["financial"]["gross_revenue"] == 500

    def test_get_alerts_critical_margin(self):
        snap = StoreSnapshot()
        snap.financial = {"critical_alerts": 2}
        alerts = snap.get_alerts()
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "critical"

    def test_get_alerts_stockout(self):
        snap = StoreSnapshot()
        snap.inventory = {"stockout_risk": True, "out_of_stock_count": 3, "low_stock_count": 5}
        alerts = snap.get_alerts()
        assert any(a["type"] == "inventory" for a in alerts)

    def test_persist_and_load(self):
        snap = StoreSnapshot()
        snap.update_financial({"pnl": {"gross_revenue": 999, "net_profit": 100}})
        snap.finalize("persist_test")
        snap.persist()

        loaded = StoreSnapshot.load()
        assert loaded.financial["gross_revenue"] == 999
        assert loaded.cycle_id == "persist_test"

    def test_snapshot_updated_after_cycle(self):
        c = CoreOrchestrator()
        c.run_cycle()
        assert c.snapshot.last_updated > 0
        assert c.snapshot.cycle_id != ""
        assert c.snapshot.financial.get("gross_revenue", 0) > 0


# ── PriorityEngine ──

class TestPriorityEngine:
    def test_normal_priorities(self):
        engine = PriorityEngine()
        situation = {
            "inventory": {"out_of_stock_count": 0, "low_stock_pct": 5},
            "financial": {"critical_alerts": 0, "health_grade": "B"},
            "customers": {"churn_risk_pct": 10},
            "marketing": {"optimization_actions": 1},
            "health": {"overall_grade": "B"},
            "events": [],
        }
        priorities = engine.compute(situation)
        assert len(priorities) == 5
        assert all(p["urgency"] == "normal" for p in priorities)

    def test_critical_inventory(self):
        engine = PriorityEngine()
        situation = {
            "inventory": {"out_of_stock_count": 3, "low_stock_pct": 40},
            "financial": {"critical_alerts": 0, "health_grade": "B"},
            "customers": {"churn_risk_pct": 10},
            "marketing": {"optimization_actions": 0},
            "health": {"overall_grade": "B"},
            "events": [],
        }
        priorities = engine.compute(situation)
        inv = next(p for p in priorities if p["domain"] == "inventory")
        assert inv["urgency"] == "critical"
        assert inv["score"] >= 100

    def test_critical_financial(self):
        engine = PriorityEngine()
        situation = {
            "inventory": {"out_of_stock_count": 0, "low_stock_pct": 0},
            "financial": {"critical_alerts": 2, "health_grade": "F"},
            "customers": {"churn_risk_pct": 0},
            "marketing": {"optimization_actions": 0},
            "health": {"overall_grade": "B"},
            "events": [],
        }
        priorities = engine.compute(situation)
        fin = next(p for p in priorities if p["domain"] == "financial")
        assert fin["urgency"] == "critical"

    def test_goal_affects_priority(self):
        engine = PriorityEngine()
        situation = {
            "inventory": {"out_of_stock_count": 0, "low_stock_pct": 0},
            "financial": {"critical_alerts": 0, "health_grade": "B"},
            "customers": {"churn_risk_pct": 0},
            "marketing": {"optimization_actions": 0},
            "health": {"overall_grade": "B"},
            "events": [],
        }
        p_profit = engine.compute(situation, goal="maximize_profit")
        p_growth = engine.compute(situation, goal="grow_customers")
        # Financial should rank higher for profit goal
        profit_fin = next(p for p in p_profit if p["domain"] == "financial")
        growth_fin = next(p for p in p_growth if p["domain"] == "financial")
        assert profit_fin["score"] >= growth_fin["score"]

    def test_has_critical(self):
        engine = PriorityEngine()
        assert engine.has_critical({"inventory": {"out_of_stock_count": 1}})
        assert not engine.has_critical({"inventory": {"out_of_stock_count": 0}})

    def test_get_focus_domains(self):
        engine = PriorityEngine()
        situation = {
            "inventory": {"out_of_stock_count": 5, "low_stock_pct": 50},
            "financial": {"critical_alerts": 3, "health_grade": "F"},
            "customers": {"churn_risk_pct": 80},
            "marketing": {"optimization_actions": 0},
            "health": {"overall_grade": "B"},
            "events": [],
        }
        focus = engine.get_focus_domains(situation, max_domains=2)
        assert len(focus) == 2
        # Top 2 should be critical domains
        assert all(d in ("inventory", "financial", "customers") for d in focus)

    def test_recommended_actions(self):
        engine = PriorityEngine()
        situation = {"inventory": {"out_of_stock_count": 1}}
        priorities = engine.compute(situation)
        inv = next(p for p in priorities if p["domain"] == "inventory")
        assert len(inv["recommended_actions"]) > 0


# ── ActionCoordinator ──

class TestActionCoordinator:
    def test_first_action_allowed(self):
        ac = ActionCoordinator()
        verdict = ac.check("price_increase", "prod_1")
        assert verdict["allowed"] is True

    def test_cooldown_blocks_repeat(self):
        ac = ActionCoordinator()
        ac.record("price_increase", "prod_1")
        verdict = ac.check("price_increase", "prod_1")
        assert verdict["allowed"] is False
        assert "Cooldown" in verdict["reason"]

    def test_different_target_allowed(self):
        ac = ActionCoordinator()
        ac.record("price_increase", "prod_1")
        verdict = ac.check("price_increase", "prod_2")
        assert verdict["allowed"] is True

    def test_conflict_blocks(self):
        ac = ActionCoordinator()
        ac.record("price_increase", "prod_1")
        verdict = ac.check("price_decrease", "prod_1")
        assert verdict["allowed"] is False
        assert "Conflicts" in verdict["reason"]

    def test_in_flight_blocks_duplicate(self):
        ac = ActionCoordinator()
        ac.start_action("ad_launch", "camp_1")
        verdict = ac.check("ad_launch", "camp_1")
        assert verdict["allowed"] is False
        assert "in-flight" in verdict["reason"]

    def test_finish_action_clears_in_flight(self):
        ac = ActionCoordinator()
        ac.start_action("ad_launch", "camp_1")
        assert len(ac.get_in_flight()) == 1
        ac.finish_action("ad_launch", "camp_1")
        assert len(ac.get_in_flight()) == 0

    def test_risk_assessment(self):
        ac = ActionCoordinator()
        verdict = ac.check("price_increase", "prod_1")
        assert verdict["risk"] == "high"
        verdict2 = ac.check("content_publish", "page_1")
        assert verdict2["risk"] == "low"

    def test_get_stats(self):
        ac = ActionCoordinator()
        ac.record("price_increase", "prod_1")
        ac.record("ad_launch", "camp_1")
        ac.record("price_increase", "prod_2", result="failed")
        stats = ac.get_stats()
        assert stats["total_actions"] == 3
        assert stats["by_type"]["price_increase"] == 2
        assert stats["by_result"]["success"] == 2
        assert stats["by_result"]["failed"] == 1

    def test_recent_actions(self):
        ac = ActionCoordinator()
        ac.record("price_increase", "prod_1")
        ac.record("ad_launch", "camp_1")
        recent = ac.get_recent_actions(limit=5)
        assert len(recent) == 2
        # Filter by type
        price_only = ac.get_recent_actions(action_type="price_increase")
        assert len(price_only) == 1


# ── CycleJournal ──

class TestCycleJournal:
    def test_record_cycle(self):
        journal = CycleJournal(journal_dir="/tmp/shopai_test_journal")
        entry_id = journal.record_cycle({
            "cycle_id": "test_1",
            "goal": "maximize_profit",
            "timestamp": time.time(),
            "elapsed_seconds": 0.5,
            "summary": {
                "decision": "launch product",
                "confidence": "high",
                "confidence_score": 85,
                "data_quality": 90,
                "health_grade": "A",
                "events_fired": 2,
                "modules_active": 12,
            },
        })
        assert entry_id.startswith("journal_")

    def test_record_event(self):
        journal = CycleJournal(journal_dir="/tmp/shopai_test_journal2")
        entry_id = journal.record_event("revenue.drop", {"amount": -500})
        assert entry_id.startswith("event_")

    def test_get_recent(self):
        journal = CycleJournal(journal_dir="/tmp/shopai_test_journal3")
        journal.record_cycle({"cycle_id": "c1", "timestamp": time.time(), "summary": {}})
        journal.record_cycle({"cycle_id": "c2", "timestamp": time.time(), "summary": {}})
        recent = journal.get_recent(hours=1)
        assert len(recent) >= 2

    def test_get_decisions(self):
        import tempfile
        journal = CycleJournal(journal_dir=tempfile.mkdtemp())
        journal.record_cycle({"cycle_id": "c1", "timestamp": time.time(), "goal": "g1", "summary": {}})
        journal.record_event("e1", {})
        journal.record_cycle({"cycle_id": "c2", "timestamp": time.time(), "goal": "g2", "summary": {}})
        decisions = journal.get_decisions()
        assert len(decisions) == 2

    def test_get_stats(self):
        import tempfile
        journal = CycleJournal(journal_dir=tempfile.mkdtemp())
        journal.record_cycle({"cycle_id": "c1", "timestamp": time.time(), "goal": "maximize_profit",
                              "summary": {"confidence_score": 80}})
        journal.record_cycle({"cycle_id": "c2", "timestamp": time.time(), "goal": "grow_customers",
                              "summary": {"confidence_score": 60}})
        stats = journal.get_stats()
        assert stats["total_cycles"] == 2
        assert stats["avg_confidence_score"] == 70.0

    def test_detect_patterns_repeated_decision(self):
        journal = CycleJournal(journal_dir="/tmp/shopai_test_journal6")
        for i in range(5):
            journal.record_cycle({
                "cycle_id": f"c{i}", "timestamp": time.time(),
                "summary": {"decision": "same_decision", "confidence_score": 50},
            })
        patterns = journal.detect_patterns()
        assert any(p["type"] == "repeated_decision" for p in patterns)

    def test_detect_patterns_declining_confidence(self):
        journal = CycleJournal(journal_dir="/tmp/shopai_test_journal7")
        for score in [90, 80, 70, 60, 50]:
            journal.record_cycle({
                "cycle_id": f"c{score}", "timestamp": time.time(),
                "summary": {"decision": f"d{score}", "confidence_score": score},
            })
        patterns = journal.detect_patterns()
        assert any(p["type"] == "declining_confidence" for p in patterns)


# ── Full Integration ──

class TestCycleIntegration:
    def test_financial_data_flows_to_intelligence(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        assert result["phases"]["financial"]["pnl"]["gross_revenue"] > 0
        assert result["phases"]["intelligence"]["stages_completed"] == 7

    def test_events_react_to_cycle(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        assert "events_fired" in result["phases"]["events"]

    def test_events_phase_survives_list_optimization(self):
        """Regression for AUDIT_LOG P2 (2026-04-20).

        _phase_campaigns stores optimizer.optimize() output directly,
        which is a list of action dicts. _phase_events then reads
        ``campaigns["optimization"]`` and previously called .get() on
        it, crashing with AttributeError and producing no events.
        """
        c = CoreOrchestrator()
        cfg = {
            "campaigns": [
                {
                    "campaign_id": "c1",
                    "roas": 1.2, "ctr": 0.5, "cpc": 1.0,
                    "budget": 100, "spend": 50, "revenue": 60,
                    "status": "active",
                },
            ],
        }
        result = c.run_cycle(config=cfg)
        events = result["phases"]["events"]
        assert "events_fired" in events
        # Pause verdict on c1 should have fired an underperform event
        details = events.get("details", [])
        assert any(
            "campaign.underperform" in d for d in details
        ), f"expected underperform event, got {details}"

    def test_kpi_recorded(self):
        c = CoreOrchestrator()
        c.run_cycle()
        kpi = c.get_module("kpi_tracker")
        assert kpi.get_decision_kpis().get("total_decisions", 0) >= 1

    def test_snapshot_updated_after_cycle(self):
        c = CoreOrchestrator()
        c.run_cycle()
        assert c.snapshot.last_updated > 0
        assert c.snapshot.financial.get("gross_revenue", 0) > 0
        assert c.snapshot.inventory.get("total_products", 0) > 0
        assert c.snapshot.products.get("stages_completed", 0) == 7

    def test_journal_records_cycle(self):
        c = CoreOrchestrator()
        c.run_cycle()
        stats = c.journal.get_stats()
        assert stats["total_cycles"] >= 1

    def test_situation_available(self):
        c = CoreOrchestrator()
        c.run_cycle()
        situation = c.get_situation()
        assert "financial" in situation
        assert "inventory" in situation
        assert "alerts" in situation
        assert "patterns" in situation

    def test_action_coordination_works(self):
        c = CoreOrchestrator()
        result1 = c.execute_action("price_increase", "prod_1")
        assert result1["status"] == "executed"
        result2 = c.execute_action("price_increase", "prod_1")
        assert result2["status"] == "blocked"

    def test_react_records_event(self):
        c = CoreOrchestrator()
        c.react("product.price_change", {"source": "competitor"})
        stats = c.journal.get_stats()
        assert stats["total_events"] >= 1

    def test_multi_cycle_history(self):
        c = CoreOrchestrator()
        c.run_cycle()
        c.run_cycle()
        c.run_cycle()
        assert c.status()["cycles_completed"] == 3
        assert c.status()["journal_entries"] >= 3

    def test_new_phases_present(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        for phase in ["financial_depth", "marketing_tactics", "customer_journey", "supply_chain"]:
            assert phase in result["phases"], f"Phase {phase} missing"
            assert result["phases"][phase].get("status") != "error", f"Phase {phase} errored"


# ── New Intelligence Modules ──

class TestFinancialDepth:
    def test_bnpl_analysis(self):
        from core.intelligence.financial_depth import FinancialDepth
        fd = FinancialDepth()
        products = [{"id": 1, "price": 75, "cost": 30}]
        orders = [{"total": 75}, {"total": 100}]
        result = fd.analyze_bnpl(products, orders)
        assert result["suitable_for_bnpl"] is True
        assert len(result["providers"]) == 4
        assert result["recommendation"] in ("afterpay", "klarna", "affirm", "shop_pay_installments")

    def test_tax_nexus(self):
        from core.intelligence.financial_depth import FinancialDepth
        fd = FinancialDepth()
        result = fd.analyze_tax_nexus({"CA": 600000, "TX": 50000})
        assert result["states_with_nexus"] == 1
        assert result["total_estimated_tax"] > 0
        assert result["action_needed"] is True

    def test_chargeback_risk(self):
        from core.intelligence.financial_depth import FinancialDepth
        fd = FinancialDepth()
        orders = [{"total": 50, "financial_status": "paid"} for _ in range(100)]
        result = fd.assess_chargeback_risk(orders)
        assert result["risk_level"] == "low"
        assert result["total_orders"] == 100

    def test_payment_processor_comparison(self):
        from core.intelligence.financial_depth import FinancialDepth
        fd = FinancialDepth()
        orders = [{"total": 50} for _ in range(100)]
        result = fd.optimize_payment_processor(orders)
        assert len(result["comparisons"]) == 4
        assert "cheapest" in result

    def test_contribution_margin(self):
        from core.intelligence.financial_depth import FinancialDepth
        fd = FinancialDepth()
        products = [{"id": "1", "title": "Widget", "price": 50, "cost": 15}]
        orders = [{"line_items": [{"product_id": "1", "price": 50, "quantity": 2, "cost": 15}]}]
        result = fd.contribution_margin_by_sku(products, orders)
        assert result["skus_analyzed"] == 1
        assert result["details"][0]["contribution_margin"] > 0

    def test_working_capital(self):
        from core.intelligence.financial_depth import FinancialDepth
        fd = FinancialDepth()
        orders = [{"total": 100} for _ in range(30)]
        result = fd.analyze_working_capital(orders)
        assert "cash_conversion_cycle_days" in result
        assert "daily_revenue" in result


class TestMarketingTactics:
    def test_creative_fatigue_detection(self):
        from core.intelligence.marketing_tactics import MarketingTactics
        mt = MarketingTactics()
        campaigns = [
            {"name": "camp1", "days_running": 25, "ctr": 0.5, "ctr_7d_ago": 1.5, "frequency": 4, "cpa": 20, "cpa_7d_ago": 10},
        ]
        result = mt.detect_creative_fatigue(campaigns)
        assert result["fatigued_campaigns"] == 1

    def test_social_proof_audit(self):
        from core.intelligence.marketing_tactics import MarketingTactics
        mt = MarketingTactics()
        products = [
            {"title": "A", "review_count": 0, "rating": 0},
            {"title": "B", "review_count": 20, "rating": 4.5, "has_photo_reviews": True},
        ]
        result = mt.audit_social_proof(products)
        assert result["weak_social_proof"] >= 1

    def test_influencer_strategy(self):
        from core.intelligence.marketing_tactics import MarketingTactics
        mt = MarketingTactics()
        products = [{"price": 50}]
        result = mt.plan_influencer_strategy(products)
        assert result["recommended_tier"] in ("nano", "micro", "mid", "macro")

    def test_referral_opportunity(self):
        from core.intelligence.marketing_tactics import MarketingTactics
        mt = MarketingTactics()
        customers = [{"orders_count": 3}, {"orders_count": 1}, {"orders_count": 5}]
        result = mt.analyze_referral_opportunity(customers)
        assert result["total_customers"] == 3
        assert result["repeat_customers"] == 2

    def test_email_segments(self):
        from core.intelligence.marketing_tactics import MarketingTactics
        mt = MarketingTactics()
        result = mt.recommend_email_segments([])
        assert len(result["segments"]) == 7


class TestCustomerJourney:
    def test_lifecycle_segmentation(self):
        from core.intelligence.customer_journey import CustomerJourney
        cj = CustomerJourney()
        customers = [
            {"id": 1, "orders_count": 0},
            {"id": 2, "orders_count": 1, "days_since_last_order": 5},
            {"id": 3, "orders_count": 3, "days_since_last_order": 10},
            {"id": 4, "orders_count": 6, "days_since_last_order": 15},
            {"id": 5, "orders_count": 2, "days_since_last_order": 75},
        ]
        result = cj.segment_by_lifecycle(customers)
        segs = result["segments"]
        assert segs["prospect"]["count"] == 1
        assert segs["loyal"]["count"] == 1
        assert segs["at_risk"]["count"] == 1

    def test_journey_funnel(self):
        from core.intelligence.customer_journey import CustomerJourney
        cj = CustomerJourney()
        customers = [
            {"orders_count": 0}, {"orders_count": 1}, {"orders_count": 2},
            {"orders_count": 3}, {"orders_count": 6},
        ]
        result = cj.map_customer_journeys(customers)
        assert len(result["funnel"]) == 4
        assert "biggest_dropoff" in result

    def test_landing_page_strategy(self):
        from core.intelligence.customer_journey import CustomerJourney
        cj = CustomerJourney()
        result = cj.recommend_landing_pages()
        assert "facebook_ad" in result["strategy"]
        assert "google_search" in result["strategy"]


class TestSupplyChain:
    def test_reorder_points(self):
        from core.intelligence.supply_chain import SupplyChainIntelligence
        sc = SupplyChainIntelligence()
        products = [
            {"id": "1", "title": "Widget", "inventory_quantity": 5, "cost": 10},
        ]
        orders = [
            {"line_items": [{"product_id": "1", "quantity": 2}]},
            {"line_items": [{"product_id": "1", "quantity": 3}]},
        ]
        result = sc.analyze_reorder_points(products, orders)
        assert result["products_analyzed"] == 1
        details = result["details"][0]
        assert details["reorder_point"] > 0

    def test_shipping_threshold(self):
        from core.intelligence.supply_chain import SupplyChainIntelligence
        sc = SupplyChainIntelligence()
        orders = [{"total": 50}, {"total": 70}, {"total": 80}]
        result = sc.optimize_shipping_threshold([], orders)
        assert result["recommended_threshold"] > result["current_aov"]

    def test_returns_analysis(self):
        from core.intelligence.supply_chain import SupplyChainIntelligence
        sc = SupplyChainIntelligence()
        orders = [{"total": 50, "financial_status": "paid"} for _ in range(10)]
        orders.append({"total": 60, "financial_status": "refunded"})
        result = sc.analyze_returns(orders)
        assert result["return_rate"] > 0
        assert result["true_cost_per_return"] > 0

    def test_fulfillment_recommendation(self):
        from core.intelligence.supply_chain import SupplyChainIntelligence
        sc = SupplyChainIntelligence()
        orders = [{"total": 50} for _ in range(30)]
        result = sc.recommend_fulfillment_model(orders)
        assert result["recommendation"] in ("self_fulfillment", "3pl")

    def test_dead_stock_detection(self):
        from core.intelligence.supply_chain import SupplyChainIntelligence
        sc = SupplyChainIntelligence()
        products = [
            {"id": "1", "title": "Active", "inventory_quantity": 10, "cost": 5, "days_since_last_sale": 10},
            {"id": "2", "title": "Dead", "inventory_quantity": 50, "cost": 8, "days_since_last_sale": 200},
        ]
        result = sc.detect_dead_stock(products)
        assert result["dead_stock_items"] >= 1
        assert result["total_capital_tied_up"] > 0


# ── Thinking Layers ──

class TestGoalManager:
    def test_default_goal(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        result = gm.select_goal({})
        assert result["goal"] == "maximize_profit"

    def test_crisis_goal(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        situation = {"financial": {"health_grade": "F", "critical_alerts": 3}}
        result = gm.select_goal(situation)
        assert result["goal"] == "survive_crisis"
        assert result["priority"] == 1

    def test_churn_goal(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        situation = {"customers": {"churn_risk_pct": 55}}
        result = gm.select_goal(situation)
        assert result["goal"] == "grow_customers"

    def test_hysteresis(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        gm.select_goal({}, cycle_number=1)
        # Try to switch to increase_aov too soon (within 5 cycles)
        # aov_below_median is priority 4, should be blocked by hysteresis
        result = gm.select_goal({"financial": {"aov": 20}}, cycle_number=3)
        assert result["goal"] == "maximize_profit"  # Hysteresis keeps current

    def test_urgent_overrides_hysteresis(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        gm.select_goal({}, cycle_number=1)
        # Crisis overrides hysteresis (priority 1)
        result = gm.select_goal({"financial": {"health_grade": "F", "critical_alerts": 2}}, cycle_number=2)
        assert result["goal"] == "survive_crisis"
        assert result["switched"] is True

    def test_alternatives_included(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        result = gm.select_goal({})
        assert "alternatives" in result


class TestEpisodicMemory:
    def test_record_and_recall(self):
        import tempfile
        from core.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(episodes_dir=tempfile.mkdtemp())
        mem.record_episode(
            decision_type="pricing",
            action="increase_price",
            context={"health_grade": "B", "churn_pct": 10, "confidence_score": 70},
            outcome={"success": True},
        )
        similar = mem.recall_similar({"health_grade": "B", "churn_pct": 12, "confidence_score": 65})
        assert len(similar) >= 1

    def test_get_failures(self):
        import tempfile
        from core.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(episodes_dir=tempfile.mkdtemp())
        mem.record_episode("pricing", "increase", {"health_grade": "C"}, {"success": False})
        mem.record_episode("pricing", "decrease", {"health_grade": "B"}, {"success": True})
        failures = mem.get_failures("pricing")
        assert len(failures) == 1
        assert failures[0]["action"] == "increase"

    def test_get_lessons(self):
        import tempfile
        from core.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(episodes_dir=tempfile.mkdtemp())
        mem.record_episode("launch", "new_product", {}, {"success": True})
        lessons = mem.get_lessons("launch")
        assert len(lessons) == 1
        assert "succeeded" in lessons[0]["lesson"]

    def test_success_rate(self):
        import tempfile
        from core.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(episodes_dir=tempfile.mkdtemp())
        for i in range(7):
            mem.record_episode("test", "action", {}, {"success": i < 5})
        rate = mem.get_success_rate("test")
        assert rate["success_rate"] == pytest.approx(71.4, abs=0.1)

    def test_persist_and_load(self):
        import tempfile
        d = tempfile.mkdtemp()
        from core.memory.episodic_memory import EpisodicMemory
        mem = EpisodicMemory(episodes_dir=d)
        mem.record_episode("test", "action", {"x": 1}, {"success": True})
        # Load fresh
        mem2 = EpisodicMemory(episodes_dir=d)
        assert mem2.get_stats()["total_episodes"] == 1


class TestJudgmentAdvisor:
    def test_proceed_on_good_conditions(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        decision = {"action": "Launch Widget", "confidence_score": 75, "options_evaluated": 4}
        situation = {"health": {"overall_grade": "B"}, "financial": {"health_grade": "B"}, "events": []}
        result = advisor.evaluate(decision, situation)
        assert result["verdict"] == "proceed"

    def test_risk_score_increases_with_bad_conditions(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        # Good conditions
        good = advisor.evaluate(
            {"action": "test", "confidence_score": 90, "options_evaluated": 5},
            {"health": {"overall_grade": "A"}, "financial": {"health_grade": "A"}, "events": []},
        )
        # Bad conditions
        bad = advisor.evaluate(
            {"action": "Big pricing change", "confidence_score": 25, "options_evaluated": 1},
            {"health": {"overall_grade": "D"}, "financial": {"health_grade": "D", "critical_alerts": 2}, "events": ["competitor"]},
        )
        assert bad["risk_score"] > good["risk_score"]
        assert bad["risk_score"] > 0.3

    def test_checks_present(self):
        from core.judgment.judgment_advisor import JudgmentAdvisor
        advisor = JudgmentAdvisor()
        decision = {"action": "test", "confidence_score": 50}
        result = advisor.evaluate(decision, {})
        assert len(result["checks"]) == 7
        check_names = [c["check"] for c in result["checks"]]
        assert "magnitude" in check_names
        assert "system_stability" in check_names


class TestFailurePrevention:
    def test_no_veto_without_failures(self):
        import tempfile
        from core.memory.episodic_memory import EpisodicMemory
        from core.judgment.failure_prevention import FailureContextPrevention
        mem = EpisodicMemory(episodes_dir=tempfile.mkdtemp())
        fp = FailureContextPrevention(episodic_memory=mem)
        result = fp.check("pricing", {"health_grade": "B"})
        assert result["vetoed"] is False

    def test_veto_on_matching_failure(self):
        import tempfile
        from core.memory.episodic_memory import EpisodicMemory
        from core.judgment.failure_prevention import FailureContextPrevention
        mem = EpisodicMemory(episodes_dir=tempfile.mkdtemp())
        # Record a failure
        mem.record_episode(
            "pricing", "increase_price",
            context={"health_grade": "C", "churn_pct": 40, "stockout_risk": True, "confidence_score": 50, "net_margin": 5},
            outcome={"success": False},
        )
        fp = FailureContextPrevention(episodic_memory=mem)
        # Check with very similar context
        result = fp.check("pricing", {
            "health_grade": "C", "churn_pct": 42, "stockout_risk": True, "confidence_score": 48, "net_margin": 6,
        })
        assert result["match_score"] > 0.7
        assert result["vetoed"] is True

    def test_no_veto_different_context(self):
        import tempfile
        from core.memory.episodic_memory import EpisodicMemory
        from core.judgment.failure_prevention import FailureContextPrevention
        mem = EpisodicMemory(episodes_dir=tempfile.mkdtemp())
        mem.record_episode("pricing", "increase", {"health_grade": "F", "churn_pct": 80}, {"success": False})
        fp = FailureContextPrevention(episodic_memory=mem)
        result = fp.check("pricing", {"health_grade": "A", "churn_pct": 5})
        assert result["vetoed"] is False


class TestDecisionNarrator:
    def test_narrate_cycle(self):
        from core.intelligence.decision_narrator import DecisionNarrator
        narrator = DecisionNarrator()
        cycle_result = {
            "goal": "maximize_profit",
            "summary": {
                "decision": "Launch Widget X",
                "confidence": "high",
                "confidence_score": 85,
                "strategy_goal": "maximize_profit",
                "decision_reason": "High demand, good margins",
                "health_grade": "A",
                "net_profit": 500,
                "data_quality": 90,
            },
            "phases": {"judgment": {"verdict": "proceed"}},
            "priorities": [],
        }
        narrative = narrator.narrate(cycle_result)
        assert "Launch Widget X" in narrative
        assert "Maximize profitability" in narrative
        assert "85/100" in narrative

    def test_explain_decision(self):
        from core.intelligence.decision_narrator import DecisionNarrator
        narrator = DecisionNarrator()
        explanation = narrator.explain_decision(
            {"action": "Raise price", "confidence": "medium", "confidence_score": 60, "options_evaluated": 3},
            goal="maximize_profit",
        )
        assert "Raise price" in explanation
        assert "60/100" in explanation

    def test_summarize_situation(self):
        from core.intelligence.decision_narrator import DecisionNarrator
        narrator = DecisionNarrator()
        summary = narrator.summarize_situation({
            "financial": {"gross_revenue": 10000, "net_profit": 3000, "health_grade": "B"},
            "inventory": {"total_products": 50, "out_of_stock_count": 2, "low_stock_count": 5},
            "customers": {"total": 200, "churn_risk_pct": 15},
            "health": {},
            "alerts": [{"severity": "high", "message": "2 products out of stock"}],
        })
        assert "$10,000" in summary
        assert "2 products out of stock" in summary


class TestLegalCompliance:
    def test_supplement_detection(self):
        from core.intelligence.legal_compliance import LegalCompliance
        lc = LegalCompliance()
        result = lc.check_product({"title": "Vitamin C Supplement 1000mg", "category": "supplements"})
        assert result["category"] == "supplements"
        assert result["agency"] == "FDA"
        assert len(result["requirements"]) > 0

    def test_children_product_critical(self):
        from core.intelligence.legal_compliance import LegalCompliance
        lc = LegalCompliance()
        result = lc.check_product({"title": "Baby Toy Rattle"})
        assert result["category"] == "children"
        assert result["risk_level"] == "critical"

    def test_ad_prohibited_claims(self):
        from core.intelligence.legal_compliance import LegalCompliance
        lc = LegalCompliance()
        result = lc.check_advertising("This supplement can cure headaches and treat pain!")
        assert result["compliant"] is False
        assert len(result["violations"]) >= 1

    def test_ad_endorsement_disclosure(self):
        from core.intelligence.legal_compliance import LegalCompliance
        lc = LegalCompliance()
        result = lc.check_advertising("Our influencer ambassador says this product is amazing!")
        assert result["compliant"] is False
        assert any("disclosure" in v.lower() for v in result["violations"])

    def test_privacy_gdpr(self):
        from core.intelligence.legal_compliance import LegalCompliance
        lc = LegalCompliance()
        result = lc.check_privacy(sells_to_eu=True)
        assert "gdpr" in result["applicable_regulations"]
        assert len(result["requirements"]) > 5

    def test_full_audit(self):
        from core.intelligence.legal_compliance import LegalCompliance
        lc = LegalCompliance()
        result = lc.full_audit(
            products=[{"title": "Vitamin C Supplement"}],
            ad_content=["Buy our cure-all supplement!"],
        )
        assert result["violation_count"] > 0
        assert result["overall_compliant"] is False


# ── Thinking Layer Integration ──

class TestThinkingLayerIntegration:
    def test_all_new_phases_present(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        assert "compliance" in result["phases"]
        assert "judgment" in result["phases"]
        assert "narrative" in result

    def test_judgment_verdict_in_cycle(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        judgment = result["phases"]["judgment"]
        assert judgment["verdict"] in ("proceed", "delay", "modify", "escalate_to_human")

    def test_episode_recorded(self):
        c = CoreOrchestrator()
        c.run_cycle()
        mem = c.get_module("episodic_memory")
        assert mem.get_stats()["total_episodes"] >= 1

    def test_goal_auto_selection(self):
        c = CoreOrchestrator()
        result = c.run_cycle(goal=None)
        assert result["goal"] in ("maximize_profit", "grow_customers", "increase_aov", "survive_crisis", "capture_opportunity")

    def test_narrative_generated(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        assert len(result.get("narrative", "")) > 20
