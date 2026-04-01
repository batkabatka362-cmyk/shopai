"""Tests for CoreOrchestrator — the central brain."""
import pytest
from core.core_orchestrator import CoreOrchestrator


class TestCoreOrchestratorInit:
    """Test module initialization."""

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


class TestRunCycle:
    """Test the full intelligence cycle."""

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
        expected_phases = [
            "data", "financial", "campaigns", "competitive",
            "intelligence", "strategy", "events", "health",
        ]
        for p in expected_phases:
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
        assert "gross_revenue" in fin["pnl"]
        assert fin["pnl"]["gross_revenue"] > 0

    def test_intelligence_phase_makes_decision(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        intel = result["phases"]["intelligence"]
        assert intel.get("stages_completed") == 7
        assert "decision" in intel
        assert intel["decision"]["confidence"] in ("low", "medium", "high")
        assert 0 <= intel["decision"]["confidence_score"] <= 100

    def test_strategy_phase_has_autopilot(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        strat = result["phases"]["strategy"]
        assert "autopilot" in strat
        assert "should_switch" in strat["autopilot"]
        assert "goal_scores" in strat["autopilot"]

    def test_health_phase_has_grade(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        health = result["phases"]["health"]
        assert "overall_grade" in health
        assert health["overall_grade"] in ("A", "B", "C", "D", "F")

    def test_summary_has_key_metrics(self):
        c = CoreOrchestrator()
        result = c.run_cycle()
        summary = result["summary"]
        assert "decision" in summary
        assert "confidence" in summary
        assert "confidence_score" in summary
        assert "data_quality" in summary
        assert "modules_active" in summary
        assert summary["modules_active"] == 12

    def test_different_goals(self):
        c = CoreOrchestrator()
        for goal in ["maximize_profit", "grow_customers", "increase_aov"]:
            result = c.run_cycle(goal=goal)
            assert result["goal"] == goal
            assert result["summary"]["strategy_goal"] == goal


class TestCycleHistory:
    """Test cycle history tracking."""

    def test_history_tracks_cycles(self):
        c = CoreOrchestrator()
        c.run_cycle()
        c.run_cycle()
        history = c.get_history()
        assert len(history) == 2

    def test_history_limit(self):
        c = CoreOrchestrator()
        for _ in range(3):
            c.run_cycle()
        assert len(c.get_history(limit=2)) == 2

    def test_cycle_count_increments(self):
        c = CoreOrchestrator()
        c.run_cycle()
        c.run_cycle()
        assert c.status()["cycles_completed"] == 2


class TestCycleIntegration:
    """Test that phases feed into each other."""

    def test_financial_data_flows_to_intelligence(self):
        """Financial insights should enrich IntelligenceLoop input."""
        c = CoreOrchestrator()
        result = c.run_cycle()
        # Financial phase should produce real numbers
        fin = result["phases"]["financial"]
        assert fin["pnl"]["gross_revenue"] > 0
        # Intelligence should complete its 7 stages
        intel = result["phases"]["intelligence"]
        assert intel["stages_completed"] == 7

    def test_events_react_to_cycle(self):
        """Event reactor should process cycle results."""
        c = CoreOrchestrator()
        result = c.run_cycle()
        events = result["phases"]["events"]
        assert "events_fired" in events
        assert isinstance(events["events_fired"], int)

    def test_kpi_recorded(self):
        """KPIs should be recorded after each cycle."""
        c = CoreOrchestrator()
        result = c.run_cycle()
        kpi = c.get_module("kpi_tracker")
        kpis = kpi.get_decision_kpis()
        # At least one decision should be recorded
        assert kpis.get("total_decisions", 0) >= 1
