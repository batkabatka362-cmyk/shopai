"""Regression tests for Fix F: smart execution → learning loop.

Pre-fix Fix C closed the learning loop for manual
``DecisionEngine.record_outcome()`` calls, but the autonomous
cycle's smart-execution path was still detached: SmartExecutor
ran actions, scored them, and threw the outcomes away. The
``ActionWeightStore`` only ever accumulated data from the few
code paths that manually called ``engine.record_outcome``, so
autonomous cycles were still effectively amnesiac at the
action-weight level.

Core audit flagged this as the #3 CRITICAL weakness ("Smart
execution is detached from outcome tracking"). Fix F closes
the remaining gap by having ``AutonomousController.run_cycle``
phase 5 write every smart-execution result into the
``ActionWeightStore`` before the other learning systems run.

Key design choice: we write under ``(action_type, action_type)``
— same string for both category and action — because
SmartExecutor operates on action types, not brain decision
categories. The naming bridge between action_type (raise_price)
and brain decision option action (raise_10pct) is a separate
concern. What Fix F guarantees:

  1. Every smart execution result lands in the weight store.
  2. The cycle_result["phases"]["learning"]["weight_updates"]
     counter tells operators how many outcomes were captured.
  3. Subsequent cycles can inspect the store to see
     accumulated action-level history.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _make_controller(tmp_path):
    """Build an AutonomousController + point the
    ActionWeightStore at a disposable DB so the test can't
    pollute (or be polluted by) the real weight store."""
    from data_pipeline.store.db import ShopAIDatabase
    from data_pipeline.store.store_manager import StoreManager
    from core.autonomous.controller import AutonomousController
    from core.learning.action_weights import reset_action_weight_store

    weights_db = tmp_path / "weights.db"
    reset_action_weight_store(weights_db)

    store_db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
    sm = StoreManager(store_db)
    sm.add_store("test", "test.myshopify.com", "shpat_test")
    store_db.upsert_products("test", [
        {"id": "p1", "title": "Widget", "price": 29.99, "cost": 10,
         "status": "active", "inventory_quantity": 50},
        {"id": "p2", "title": "Gadget", "price": 49.99, "cost": 20,
         "status": "active", "inventory_quantity": 30},
    ])
    store_db.upsert_orders("test", [
        {"id": "o1", "total": 79.98, "financial_status": "paid"},
    ])
    store_db.upsert_customers("test", [
        {"id": "c1", "name": "T", "email": "t@t.com"},
    ])
    store_db.log_sync("test", "products", "success", 2, 0.1)
    store_db.log_sync("test", "orders", "success", 1, 0.1)
    store_db.log_sync("test", "customers", "success", 1, 0.1)

    ac = AutonomousController(sm, auto_approve=False)
    ac.initialize()
    return ac


class TestSmartExecFeedsWeightStore:
    def test_weight_store_receives_smart_exec_outcomes(self, tmp_path, monkeypatch):
        """THE integration test: run a full cycle with a
        faked SmartExecutor that returns deterministic
        outcomes, then verify every outcome landed in the
        ActionWeightStore."""
        from core.learning.action_weights import get_action_weight_store

        ac = _make_controller(tmp_path)

        # Replace ``SmartExecutor.execute_batch`` so we don't
        # depend on the brain producing specific decisions.
        # The fake returns two deterministic results with
        # distinct action types + scores.
        import execution.smart_executor as se_mod

        fake_results = [
            {
                "action_type": "fake_raise_price",
                "mode": "simulate",
                "score": 4.8,
                "confidence": 0.9,
                "duration_s": 0.01,
                "actual_outcome": {"success": True},
            },
            {
                "action_type": "fake_restock",
                "mode": "simulate",
                "score": 1.2,
                "confidence": 0.5,
                "duration_s": 0.01,
                "actual_outcome": {"success": False},
            },
        ]

        class _FakeSE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": len(fake_results),
                    "simulated": len(fake_results),
                    "dry_run": 0,
                    "live": 0,
                    "avg_score": sum(r["score"] for r in fake_results) / len(fake_results),
                    "results": list(fake_results),
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _FakeSE())

        # Force the controller to have pending actions so
        # phase 4a's ``if pending:`` branch fires. We mock the
        # action_executor's get_pending to return fake actions.
        ac._action_executor._pending_actions = [
            {"type": "fake_raise_price", "confidence": 0.9},
            {"type": "fake_restock", "confidence": 0.5},
        ]

        result = ac.run_cycle("test")
        assert result.get("status") == "complete"

        # Verify the weight store received both outcomes
        store = get_action_weight_store()
        raise_weight = store.get("fake_raise_price", "fake_raise_price")
        restock_weight = store.get("fake_restock", "fake_restock")

        # A single 4.8 score pulls weight toward 1.92 (0.9 * 1 + 0.1 * 1.92)
        # so it should be noticeably above neutral (1.0) but
        # nowhere near saturation after just one outcome.
        assert raise_weight > 1.0
        # A single 1.2 score pulls weight toward 0.48 by the
        # same EMA — first sample moves it below 1.0.
        assert restock_weight < 1.0

        # Surface the weight_updates counter on phases.learning
        learning = result["phases"].get("learning", {})
        assert learning.get("weight_updates") == 2

    def test_weight_store_empty_when_no_smart_exec(self, tmp_path, monkeypatch):
        """If no smart execution runs this cycle, the weight
        store receives no updates and the counter is 0."""
        from core.learning.action_weights import get_action_weight_store

        ac = _make_controller(tmp_path)

        # Make execute_batch return an empty result set
        import execution.smart_executor as se_mod

        class _EmptySE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 0, "simulated": 0, "dry_run": 0, "live": 0,
                    "avg_score": 0, "results": [],
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _EmptySE())

        result = ac.run_cycle("test")
        learning = result["phases"].get("learning", {})
        assert learning.get("weight_updates", 0) == 0

        # No entries in store
        store = get_action_weight_store()
        assert store.stats()["entries"] == 0

    def test_weight_store_failure_does_not_break_cycle(self, tmp_path, monkeypatch):
        """If the weight store raises during the Fix F
        write, the cycle must still complete and Fix B's
        phase_errors dict must capture the failure under the
        ``weight_store_update`` key."""
        ac = _make_controller(tmp_path)

        import core.learning.action_weights as aw_mod

        class _BoomStore:
            def record(self, *a, **kw):
                raise RuntimeError("forced failure")

        monkeypatch.setattr(
            aw_mod, "get_action_weight_store", lambda: _BoomStore(),
        )

        # Force a smart exec result so the Fix F write path fires
        import execution.smart_executor as se_mod

        class _SE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 1, "simulated": 1, "dry_run": 0, "live": 0,
                    "avg_score": 3.0,
                    "results": [{
                        "action_type": "fake_act",
                        "mode": "simulate",
                        "score": 3.0,
                        "duration_s": 0.01,
                    }],
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _SE())
        ac._action_executor._pending_actions = [
            {"type": "fake_act", "confidence": 0.8},
        ]

        result = ac.run_cycle("test")
        assert result.get("status") == "complete"
        # Fix B surfaced the failure
        assert "weight_store_update" in result.get("phase_errors", {})

    def test_weight_store_accumulates_across_cycles(self, tmp_path, monkeypatch):
        """Run two cycles with the same action + score and
        verify the weight updates cumulatively (second cycle
        sees a higher weight than first)."""
        from core.learning.action_weights import get_action_weight_store

        ac = _make_controller(tmp_path)

        import execution.smart_executor as se_mod

        class _SE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 1, "simulated": 1, "dry_run": 0, "live": 0,
                    "avg_score": 5.0,
                    "results": [{
                        "action_type": "consistent_action",
                        "mode": "simulate",
                        "score": 5.0,
                        "duration_s": 0.01,
                    }],
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _SE())
        ac._action_executor._pending_actions = [
            {"type": "consistent_action", "confidence": 0.9},
        ]

        # Cycle 1
        ac.run_cycle("test")
        store = get_action_weight_store()
        w1 = store.get("consistent_action", "consistent_action")

        # Cycle 2 (need to repopulate pending since phase 4a
        # clears it after execution)
        ac._action_executor._pending_actions = [
            {"type": "consistent_action", "confidence": 0.9},
        ]
        ac.run_cycle("test")
        w2 = store.get("consistent_action", "consistent_action")

        # EMA: each cycle pushes weight further toward 2.0
        assert w2 > w1
        assert w1 > 1.0  # first cycle already moved above neutral


class TestWeightStoreSurfacedInCycleResult:
    """The Fix F weight_updates counter must be on the
    learning phase so operators can see it in cycle output."""

    def test_learning_phase_carries_weight_updates_field(self, tmp_path):
        ac = _make_controller(tmp_path)
        result = ac.run_cycle("test")
        learning = result["phases"].get("learning", {})
        # Field is always present (even as 0)
        assert "weight_updates" in learning
        assert isinstance(learning["weight_updates"], int)
        assert learning["weight_updates"] >= 0
