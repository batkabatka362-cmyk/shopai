"""Regression tests for Fix N: weight store failure
observability.

Pre-fix, the Fix F weight-store write loop in
``AutonomousController.run_cycle`` wrapped the ENTIRE loop
in a single try/except. Three problems:

  1. A single record() failure exited the loop — items
     after the failed one were silently skipped, and
     ``weight_updates`` reported a truncated count.
  2. Failures logged at WARNING level only, so operators
     scanning for ERRORS never saw them.
  3. No failure counter on the cycle summary, so
     dashboards couldn't show "N cycle outcomes failed to
     land in the weight store" and learning could drift
     silently from reality.

Core audit re-scan flagged this as the #4 MEDIUM weakness.
Fix N:

  * Wraps each ``weight_store.record(...)`` call in its own
    try/except so one bad item can't stop the loop.
  * Counts failures as ``weight_store_update_failures``.
  * Surfaces both counts on ``learning["weight_updates"]``
    and ``learning["weight_store_update_failures"]``.
  * When any failure occurs, logs an ERROR with the count
    (separate from the standard phase_errors WARNING write
    path, which only fires for top-level try/except).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _make_controller(tmp_path):
    from data_pipeline.store.db import ShopAIDatabase
    from data_pipeline.store.store_manager import StoreManager
    from core.autonomous.controller import AutonomousController
    from core.learning.action_weights import reset_action_weight_store

    reset_action_weight_store(tmp_path / "w.db")
    store_db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
    sm = StoreManager(store_db)
    sm.add_store("n_test", "n.myshopify.com", "shpat_t")
    store_db.upsert_products("n_test", [
        {"id": "p1", "title": "W", "price": 20, "cost": 5,
         "status": "active", "inventory_quantity": 50},
    ])
    store_db.log_sync("n_test", "products", "success", 1, 0.1)

    ac = AutonomousController(sm, auto_approve=False)
    ac.initialize()
    return ac


class TestPerItemFailureIsolation:
    """When one record() call raises, remaining items must
    still be processed and the counts must reflect both
    successes and failures."""

    def test_mixed_success_and_failure(self, tmp_path, monkeypatch):
        ac = _make_controller(tmp_path)

        # Fake smart executor returning 3 results
        import execution.smart_executor as se_mod
        results = [
            {"action_type": "good_1", "mode": "simulate", "score": 4.0, "duration_s": 0.01},
            {"action_type": "bad_one", "mode": "simulate", "score": 3.5, "duration_s": 0.01},
            {"action_type": "good_2", "mode": "simulate", "score": 2.8, "duration_s": 0.01},
        ]

        class _SE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 3, "simulated": 3, "dry_run": 0, "live": 0,
                    "avg_score": 3.43, "results": list(results),
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _SE())

        # Poison the weight store so the middle item fails
        import core.learning.action_weights as aw_mod

        real_store = aw_mod.get_action_weight_store()
        orig_record = real_store.record

        def _flaky_record(category, action, score):
            if action == "bad_one":
                raise RuntimeError("forced failure for bad_one")
            return orig_record(category, action, score)

        monkeypatch.setattr(real_store, "record", _flaky_record)

        ac._action_executor._pending_actions = [
            {"type": "good_1", "confidence": 0.9},
            {"type": "bad_one", "confidence": 0.8},
            {"type": "good_2", "confidence": 0.7},
        ]

        result = ac.run_cycle("n_test")
        assert result.get("status") == "complete"

        learning = result["phases"].get("learning", {})
        # Two successes (good_1, good_2), one failure (bad_one)
        assert learning.get("weight_updates") == 2, (
            f"expected 2 successful updates, got "
            f"{learning.get('weight_updates')} — per-item "
            f"isolation broken"
        )
        assert learning.get("weight_store_update_failures") == 1, (
            f"expected 1 failure, got "
            f"{learning.get('weight_store_update_failures')}"
        )

    def test_all_success_zero_failures(self, tmp_path, monkeypatch):
        """When nothing fails, the failure counter must be 0
        (field always present)."""
        ac = _make_controller(tmp_path)

        import execution.smart_executor as se_mod

        class _SE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 2, "simulated": 2, "dry_run": 0, "live": 0,
                    "avg_score": 3.8,
                    "results": [
                        {"action_type": "ok_a", "mode": "simulate",
                         "score": 4.0, "duration_s": 0.01},
                        {"action_type": "ok_b", "mode": "simulate",
                         "score": 3.6, "duration_s": 0.01},
                    ],
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _SE())
        ac._action_executor._pending_actions = [
            {"type": "ok_a", "confidence": 0.9},
            {"type": "ok_b", "confidence": 0.9},
        ]

        result = ac.run_cycle("n_test")
        learning = result["phases"].get("learning", {})
        assert learning.get("weight_updates") == 2
        assert learning.get("weight_store_update_failures") == 0

    def test_all_failures_reports_zero_successes(self, tmp_path, monkeypatch):
        """When every record() fails, weight_updates=0 and
        failures=count(results)."""
        ac = _make_controller(tmp_path)

        import execution.smart_executor as se_mod

        class _SE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 2, "simulated": 2, "dry_run": 0, "live": 0,
                    "avg_score": 3.0,
                    "results": [
                        {"action_type": "a", "mode": "simulate",
                         "score": 3.0, "duration_s": 0.01},
                        {"action_type": "b", "mode": "simulate",
                         "score": 3.0, "duration_s": 0.01},
                    ],
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _SE())

        import core.learning.action_weights as aw_mod
        real_store = aw_mod.get_action_weight_store()

        def _always_fail(category, action, score):
            raise RuntimeError("poison")

        monkeypatch.setattr(real_store, "record", _always_fail)

        ac._action_executor._pending_actions = [
            {"type": "a", "confidence": 0.9},
            {"type": "b", "confidence": 0.9},
        ]

        result = ac.run_cycle("n_test")
        learning = result["phases"].get("learning", {})
        assert learning.get("weight_updates") == 0
        assert learning.get("weight_store_update_failures") == 2


class TestFailureFieldsAlwaysPresent:
    """Both counters must be present in every cycle's
    learning phase, even when no smart executions happen,
    so dashboards can render without null checks."""

    def test_empty_cycle_has_zero_counters(self, tmp_path, monkeypatch):
        ac = _make_controller(tmp_path)

        import execution.smart_executor as se_mod

        class _Empty:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 0, "simulated": 0, "dry_run": 0, "live": 0,
                    "avg_score": 0, "results": [],
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _Empty())
        result = ac.run_cycle("n_test")
        learning = result["phases"].get("learning", {})
        assert learning.get("weight_updates", "missing") == 0
        assert learning.get("weight_store_update_failures", "missing") == 0


class TestStoreImportFailurePath:
    """Regression of the Fix F top-level try/except: when
    the weight store module can't even be imported, the
    cycle must still complete and ``phase_errors`` must
    carry ``weight_store_update``."""

    def test_store_module_unavailable(self, tmp_path, monkeypatch):
        ac = _make_controller(tmp_path)

        import execution.smart_executor as se_mod

        class _SE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 1, "simulated": 1, "dry_run": 0, "live": 0,
                    "avg_score": 3.0,
                    "results": [{"action_type": "x", "mode": "simulate",
                                 "score": 3.0, "duration_s": 0.01}],
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _SE())

        import core.learning.action_weights as aw_mod

        def _boom():
            raise ImportError("store module unavailable")

        monkeypatch.setattr(aw_mod, "get_action_weight_store", _boom)
        ac._action_executor._pending_actions = [
            {"type": "x", "confidence": 0.9},
        ]

        result = ac.run_cycle("n_test")
        assert result.get("status") == "complete"
        # Fix B surfaced the top-level failure
        assert "weight_store_update" in result.get("phase_errors", {})
