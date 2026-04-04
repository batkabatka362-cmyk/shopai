"""Tests for Phase 2: ActionExecutor, CLI, and Setup components."""
import json
import os
import tempfile
import time
import pytest


# ── ActionExecutor Tests ─────────────────────────────────────

class TestActionExecutor:
    """Test the execution layer."""

    def _make_executor(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from execution.action_executor import ActionExecutor
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")
        executor = ActionExecutor(sm)
        return executor

    def test_init(self):
        executor = self._make_executor()
        assert executor is not None

    def test_propose_action(self):
        executor = self._make_executor()
        action = executor.propose_action({
            "type": "update_price",
            "store_id": "test",
            "params": {"variant_id": "v1", "price": 29.99},
            "reason": "AI pricing optimization",
            "confidence": 0.85,
        })
        assert action["status"] == "pending"
        assert action["type"] == "update_price"
        assert "id" in action

    def test_pending_actions(self):
        executor = self._make_executor()
        executor.propose_action({"type": "update_price", "store_id": "test", "params": {}})
        executor.propose_action({"type": "update_product", "store_id": "test", "params": {}})
        pending = executor.get_pending()
        assert len(pending) == 2

    def test_reject_action(self):
        executor = self._make_executor()
        action = executor.propose_action({"type": "update_price", "store_id": "test", "params": {}})
        result = executor.reject_action(action["id"], "Not ready")
        assert result["status"] == "rejected"
        assert len(executor.get_pending()) == 0

    def test_auto_approve_executes_immediately(self):
        executor = self._make_executor()
        executor.set_auto_approve(True)
        # This will fail because no real Shopify, but it should attempt execution
        action = executor.propose_action({
            "type": "get_store_info",
            "store_id": "test",
            "params": {},
        })
        # Should have tried to execute (will fail since no real API)
        assert action["status"] in ("executed", "failed")

    def test_get_stats(self):
        executor = self._make_executor()
        executor.propose_action({"type": "t1", "store_id": "test", "params": {}})
        executor.propose_action({"type": "t2", "store_id": "test", "params": {}})
        stats = executor.get_stats()
        assert stats["pending"] == 2
        assert stats["executed"] == 0

    def test_reject_nonexistent_action(self):
        executor = self._make_executor()
        result = executor.reject_action("nonexistent")
        assert "error" in result

    def test_approve_nonexistent_action(self):
        executor = self._make_executor()
        result = executor.approve_action("nonexistent")
        assert "error" in result

    def test_action_log(self):
        executor = self._make_executor()
        action = executor.propose_action({"type": "t1", "store_id": "test", "params": {}})
        executor.reject_action(action["id"])
        log = executor.get_action_log()
        assert len(log) == 1
        assert log[0]["status"] == "rejected"


# ── DecisionExecutor Tests ───────────────────────────────────

class TestDecisionExecutor:
    """Test the bridge between engine output and action execution."""

    def _make_decision_executor(self):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from execution.action_executor import ActionExecutor, DecisionExecutor
        tmp = tempfile.mktemp(suffix=".db")
        db = ShopAIDatabase(tmp)
        sm = StoreManager(db)
        sm.add_store("test", "test.myshopify.com", "shpat_test")
        ae = ActionExecutor(sm)
        return DecisionExecutor(ae), ae

    def test_pricing_decisions(self):
        de, ae = self._make_decision_executor()
        pricing_output = {
            "data": {
                "recommendations": [
                    {"variant_id": "v1", "new_price": 34.99, "confidence": 0.9, "reason": "Competitor lower"},
                    {"variant_id": "v2", "new_price": 19.99, "confidence": 0.8, "reason": "Low demand"},
                ]
            }
        }
        actions = de.execute_pricing_decisions("test", pricing_output)
        assert len(actions) == 2
        assert all(a["type"] == "update_price" for a in actions)
        assert len(ae.get_pending()) == 2

    def test_inventory_decisions(self):
        de, ae = self._make_decision_executor()
        inventory_output = {
            "data": {
                "recommendations": [
                    {"inventory_item_id": "inv1", "location_id": "loc1", "quantity": 100, "confidence": 0.95},
                ]
            }
        }
        actions = de.execute_inventory_decisions("test", inventory_output)
        assert len(actions) == 1
        assert actions[0]["type"] == "update_inventory"

    def test_product_decisions_create(self):
        de, ae = self._make_decision_executor()
        product_output = {
            "data": {
                "recommendations": [
                    {"action": "create", "product_data": {"title": "New Widget"}, "confidence": 0.7},
                ]
            }
        }
        actions = de.execute_product_decisions("test", product_output)
        assert len(actions) == 1
        assert actions[0]["type"] == "create_product"

    def test_empty_recommendations(self):
        de, ae = self._make_decision_executor()
        actions = de.execute_pricing_decisions("test", {"data": {"recommendations": []}})
        assert len(actions) == 0


# ── CLI Tests ────────────────────────────────────────────────

class TestCLI:
    """Test CLI commands."""

    def test_build_parser(self):
        from cli import build_parser
        parser = build_parser()
        assert parser is not None

    def test_engines_command(self, capsys):
        from cli import main
        main(["engines"])
        captured = capsys.readouterr()
        assert "Registered engines:" in captured.out

    def test_health_command(self, capsys):
        from cli import main
        main(["health"])
        captured = capsys.readouterr()
        assert "ShopAI Health Check" in captured.out

    def test_status_command(self, capsys):
        from cli import main
        main(["status"])
        captured = capsys.readouterr()
        assert "ShopAI System Status" in captured.out

    def test_setup_no_env(self, capsys):
        from cli import main
        # Should show instructions when no .env
        old_env = os.environ.pop("SHOPAI_SHOPIFY_URL", None)
        old_key = os.environ.pop("SHOPAI_SHOPIFY_KEY", None)
        try:
            main(["setup"])
        except SystemExit:
            pass
        captured = capsys.readouterr()
        # Should contain some setup info
        assert "ShopAI" in captured.out or "setup" in captured.out.lower() or "store" in captured.out.lower()
        if old_env:
            os.environ["SHOPAI_SHOPIFY_URL"] = old_env
        if old_key:
            os.environ["SHOPAI_SHOPIFY_KEY"] = old_key

    def test_store_list_empty(self, capsys):
        from cli import main
        main(["store", "list"])
        captured = capsys.readouterr()
        assert "Store" in captured.out or "store" in captured.out

    def test_actions_pending_empty(self, capsys):
        from cli import main
        main(["actions", "pending"])
        captured = capsys.readouterr()
        assert "pending" in captured.out.lower() or "No" in captured.out


# ── Setup Tests ──────────────────────────────────────────────

class TestSetup:
    """Test setup and connection."""

    def test_setup_status(self):
        from infrastructure.setup import ShopAISetup
        setup = ShopAISetup()
        status = setup.get_setup_status()
        assert "env_file" in status
        assert "stores" in status

    def test_create_env(self):
        from infrastructure.setup import ShopAISetup
        setup = ShopAISetup()
        # Override path to temp
        setup._env_path = tempfile.mktemp(suffix=".env")
        from pathlib import Path
        setup._env_path = Path(setup._env_path)
        path = setup.create_env({
            "shop_url": "test.myshopify.com",
            "api_key": "shpat_test123",
        })
        content = Path(path).read_text()
        assert "test.myshopify.com" in content
        assert "shpat_test123" in content
        # Cleanup
        Path(path).unlink(missing_ok=True)

    def test_setup_store(self):
        from infrastructure.setup import ShopAISetup
        setup = ShopAISetup()
        setup._env_path = tempfile.mktemp(suffix=".env")
        from pathlib import Path
        setup._env_path = Path(setup._env_path)
        result = setup.setup_store("test.myshopify.com", "shpat_test")
        assert result["status"] == "complete"
        assert len(result["steps"]) >= 3
        # Cleanup
        setup._env_path.unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
