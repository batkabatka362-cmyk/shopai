"""Tests for CoreOrchestrator — the central brain + all coordination components."""
import time
import pytest
from core.core_orchestrator import CoreOrchestrator
from core.orchestrator.store_snapshot import StoreSnapshot
from core.orchestrator.priority_engine import PriorityEngine
from core.orchestrator.action_coordinator import ActionCoordinator
from core.orchestrator.cycle_journal import CycleJournal


# ── CoreOrchestrator Init ──

class TestCoreOrchestratorInit:
    def test_all_modules_load(self):
        c = CoreOrchestrator()
        status = c.status()
        assert status["initialized"] is True
        assert status["modules_count"] == 12

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
        assert summary["modules_active"] == 12

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
