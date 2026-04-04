"""Tests for Phase 3: AutonomousController, LearningPipeline, PerformanceTracker."""
import tempfile
import time
import pytest


class TestAutonomousController:
    """Test the main autonomous loop."""

    def _make_controller(self, auto_approve=False):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import AutonomousController
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")
        # Add mock data so engines have something to work with
        db.upsert_products("test", [
            {"id": "p1", "title": "Test Widget", "price": 29.99, "cost": 10, "status": "active"},
            {"id": "p2", "title": "Test Gadget", "price": 49.99, "cost": 20, "status": "active"},
        ])
        db.upsert_orders("test", [
            {"id": "o1", "total": 79.98, "financial_status": "paid"},
        ])
        db.upsert_customers("test", [
            {"id": "c1", "name": "Test Customer", "email": "test@test.com"},
        ])
        db.log_sync("test", "products", "success", 2, 0.1)
        db.log_sync("test", "orders", "success", 1, 0.1)
        db.log_sync("test", "customers", "success", 1, 0.1)
        controller = AutonomousController(sm, auto_approve=auto_approve)
        controller.initialize()
        return controller

    def test_init(self):
        controller = self._make_controller()
        assert controller is not None

    def test_run_cycle(self):
        controller = self._make_controller()
        result = controller.run_cycle("test")
        assert result["status"] == "complete"
        assert result["store_id"] == "test"
        assert "phases" in result
        assert "data" in result["phases"]
        assert "analysis" in result["phases"]
        assert "decisions" in result["phases"]
        assert "learning" in result["phases"]

    def test_cycle_has_data(self):
        controller = self._make_controller()
        result = controller.run_cycle("test")
        data = result["phases"]["data"]
        # Should have at least mock data
        assert data.get("products", 0) >= 0
        assert data.get("source") in ("database", "mock")

    def test_cycle_runs_analysis(self):
        controller = self._make_controller()
        result = controller.run_cycle("test")
        analysis = result["phases"]["analysis"]
        assert analysis.get("engines_run", 0) > 0

    def test_cycle_increments_count(self):
        controller = self._make_controller()
        controller.run_cycle("test")
        controller.run_cycle("test")
        status = controller.get_status()
        assert status["cycles_completed"] == 2

    def test_get_status(self):
        controller = self._make_controller()
        status = controller.get_status()
        assert "running" in status
        assert "cycles_completed" in status
        assert "auto_approve" in status

    def test_get_history(self):
        controller = self._make_controller()
        controller.run_cycle("test")
        history = controller.get_history()
        assert len(history) == 1

    def test_no_store_returns_error(self):
        from core.autonomous.controller import AutonomousController
        controller = AutonomousController()
        controller.initialize()
        result = controller.run_cycle("")
        assert result["status"] == "error"


class TestLearningPipeline:
    """Test the learning integration."""

    def _make_pipeline(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import LearningPipeline
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")
        return LearningPipeline(sm)

    def test_init(self):
        pipeline = self._make_pipeline()
        assert pipeline is not None

    def test_process_cycle(self):
        pipeline = self._make_pipeline()
        result = pipeline.process_cycle(
            store_id="test",
            cycle_id="test_cycle_1",
            analysis_results={
                "pricing": {"status": "success", "data": {"recommendations": [
                    {"type": "lower_price", "confidence": 0.85, "impact": "high"},
                ]}},
            },
            execution_results=[],
        )
        assert result["status"] == "complete"
        assert result["decisions_recorded"] >= 1
        assert result["patterns_found"] >= 1

    def test_process_cycle_with_executions(self):
        pipeline = self._make_pipeline()
        result = pipeline.process_cycle(
            store_id="test",
            cycle_id="test_cycle_2",
            analysis_results={"pricing": {"status": "success", "data": {"recommendations": []}}},
            execution_results=[
                {"engine": "pricing", "type": "update_price", "status": "executed", "duration_s": 0.5},
            ],
        )
        assert result["outcomes_recorded"] >= 1

    def test_get_learning_summary(self):
        pipeline = self._make_pipeline()
        summary = pipeline.get_learning_summary()
        assert "weights" in summary

    def test_extract_patterns(self):
        pipeline = self._make_pipeline()
        patterns = pipeline._extract_patterns({
            "pricing": {"status": "success", "data": {"recommendations": [
                {"type": "optimize", "confidence": 0.9},
                {"type": "reduce", "confidence": 0.6},
            ]}},
        })
        assert len(patterns) == 2

    def test_empty_analysis(self):
        pipeline = self._make_pipeline()
        result = pipeline.process_cycle("test", "cycle_0", {}, [])
        assert result["status"] == "complete"
        assert result["decisions_recorded"] == 0


class TestPerformanceTracker:
    """Test performance tracking."""

    def test_init(self):
        from core.autonomous.controller import PerformanceTracker
        tracker = PerformanceTracker()
        assert tracker is not None

    def test_record_cycle(self):
        from core.autonomous.controller import PerformanceTracker
        tracker = PerformanceTracker()
        tracker.record_cycle({
            "cycle_id": "c1",
            "store_id": "s1",
            "duration_s": 5.2,
            "phases": {
                "analysis": {"insights": 3},
                "decisions": {"proposed": 2},
                "execution": {"executed": 1},
                "learning": {"weight_updates": 1},
            },
        })
        summary = tracker.get_summary()
        assert summary["total_cycles"] == 1
        assert summary["total_insights"] == 3

    def test_get_trend(self):
        from core.autonomous.controller import PerformanceTracker
        tracker = PerformanceTracker()
        # Need at least 2 cycles for trend
        for i in range(5):
            tracker.record_cycle({
                "cycle_id": f"c{i}",
                "duration_s": 1.0,
                "phases": {
                    "analysis": {"insights": i + 1},
                    "decisions": {"proposed": 1},
                    "execution": {"executed": 0},
                    "learning": {"weight_updates": 0},
                },
            })
        trend = tracker.get_trend()
        assert trend["trend"] in ("improving", "declining", "stable")

    def test_empty_summary(self):
        from core.autonomous.controller import PerformanceTracker
        tracker = PerformanceTracker()
        summary = tracker.get_summary()
        assert summary["total_cycles"] == 0


class TestCLIAutoCommands:
    """Test CLI autonomous commands."""

    def test_learn_command(self, capsys):
        from cli import main
        main(["learn"])
        captured = capsys.readouterr()
        assert "Learning" in captured.out

    def test_auto_command_no_store(self, capsys):
        from cli import main
        main(["auto"])
        captured = capsys.readouterr()
        # Should show some output (may be error or results depending on store config)
        assert len(captured.out) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
