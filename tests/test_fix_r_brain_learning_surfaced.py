"""Regression tests for Fix R: brain learning insights
surfaced + UnifiedMemory routing.

Pre-fix, ``LearningLoop.learn()`` computed rich
``failure_insight`` and ``success_insight`` dicts (root
cause, is_repeated, times_failed, recommendation) but the
controller at phase 5 only captured ``score`` and
``success`` — every richer signal was thrown away. The
controller loop over smart executions also called learn()
per item without aggregating the resulting insights, so
operators had no visibility into WHY a cycle failed or
succeeded. The insights existed, they just never reached
the cycle output.

Additionally, ``learning_loop.py`` was a Fix D violation:
it imported ``core.brain.memory.get_brain_memory`` and
``core.memory.intelligence.get_memory_intelligence``
directly, bypassing the UnifiedMemory entry point that
Fix D/I established as the single memory owner.

Core audit wave-3 #3 flagged this as a MEDIUM weakness.
Fix R:

  1. Routes ``LearningLoop`` memory access through
     ``UnifiedMemory.get_brain_memory()`` and
     ``.get_memory_intelligence()``.
  2. Aggregates per-execution insights in the controller's
     phase 5 loop into a single
     ``learning["insights"]`` list so operators can see
     all root causes + recommendations in one place.
  3. Surfaces failure / success counts on the learning
     phase summary so dashboards can render the signal.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest


class TestLearningLoopRoutesThroughUnifiedMemory:
    """AST + runtime verification that learning_loop no
    longer bypasses UnifiedMemory."""

    def test_source_has_no_direct_brain_memory_import(self):
        import re
        text = pathlib.Path("core/brain/learning_loop.py").read_text(
            encoding="utf-8",
        )
        assert not re.search(
            r"from\s+core\.brain\.memory\s+import\s+get_brain_memory",
            text,
        ), (
            "learning_loop.py still imports get_brain_memory "
            "directly — Fix R routes this through UnifiedMemory"
        )

    def test_source_has_no_direct_memory_intelligence_import(self):
        import re
        text = pathlib.Path("core/brain/learning_loop.py").read_text(
            encoding="utf-8",
        )
        assert not re.search(
            r"from\s+core\.memory\.intelligence\s+import\s+get_memory_intelligence",
            text,
        ), (
            "learning_loop.py still imports get_memory_intelligence "
            "directly — Fix R routes this through UnifiedMemory"
        )

    def test_source_uses_unified_memory(self):
        text = pathlib.Path("core/brain/learning_loop.py").read_text(
            encoding="utf-8",
        )
        assert "unified_memory" in text, (
            "learning_loop.py must import from "
            "core.memory.unified_memory after Fix R"
        )

    def test_learn_still_runs(self):
        from core.brain.learning_loop import LearningLoop
        loop = LearningLoop()
        result = loop.learn(
            "pricing",
            {"price": 100, "cost": 40},
            action="raise_10pct",
            result={"status": "success", "new_price": 110},
            metrics={"profit": 15.0},
        )
        assert isinstance(result, dict)
        assert "score" in result
        assert "success" in result


class TestLearnReturnsRichInsights:
    def test_failure_insight_returned_on_low_score(self):
        from core.brain.learning_loop import LearningLoop
        loop = LearningLoop()
        result = loop.learn(
            "pricing",
            {"price": 100, "cost": 50},
            action="raise_10pct",
            result={"status": "error", "error": "timeout"},
            metrics={"profit": -20.0},
        )
        # Score should be low → failure_insight populated
        assert result["score"] <= 2
        assert result.get("failure_insight") is not None
        assert "recommendation" in result["failure_insight"]
        assert "root_cause" in result["failure_insight"]

    def test_success_insight_returned_on_high_score(self):
        from core.brain.learning_loop import LearningLoop
        loop = LearningLoop()
        result = loop.learn(
            "pricing",
            {"price": 50, "cost": 10},
            action="raise_10pct",
            result={"status": "success"},
            metrics={"profit": 200.0, "conversion": 0.15},
        )
        assert result["score"] >= 4
        assert result.get("success_insight") is not None


class TestControllerSurfacesInsights:
    """The autonomous cycle must aggregate learn() insights
    into the learning phase summary so operators see them
    in the cycle output."""

    def _make_controller(self, tmp_path):
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import AutonomousController
        from core.learning.action_weights import reset_action_weight_store

        reset_action_weight_store(tmp_path / "w.db")
        store_db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
        sm = StoreManager(store_db)
        sm.add_store("r_test", "r.myshopify.com", "shpat_t")
        store_db.upsert_products("r_test", [
            {"id": "p1", "title": "W", "price": 20, "cost": 5,
             "status": "active", "inventory_quantity": 50},
        ])
        store_db.log_sync("r_test", "products", "success", 1, 0.1)
        ac = AutonomousController(sm, auto_approve=False)
        ac.initialize()
        return ac

    def test_learning_phase_has_brain_insights_field(self, tmp_path):
        """After a full cycle, learning["brain_insights"]
        must exist as a list (possibly empty) carrying
        the aggregated per-execution insights."""
        ac = self._make_controller(tmp_path)
        result = ac.run_cycle("r_test")
        learning = result["phases"].get("learning", {})
        assert "brain_insights" in learning, (
            f"Fix R: learning phase must expose brain_insights; "
            f"got {list(learning.keys())}"
        )
        assert isinstance(learning["brain_insights"], list)

    def test_insight_counts_on_summary(self, tmp_path):
        """Success + failure counts must be present as ints
        (zero is valid) so dashboards can render them."""
        ac = self._make_controller(tmp_path)
        result = ac.run_cycle("r_test")
        learning = result["phases"].get("learning", {})
        assert "brain_success_count" in learning
        assert "brain_failure_count" in learning
        assert isinstance(learning["brain_success_count"], int)
        assert isinstance(learning["brain_failure_count"], int)
        assert learning["brain_success_count"] >= 0
        assert learning["brain_failure_count"] >= 0

    def test_forced_failure_surfaces_insight(self, tmp_path, monkeypatch):
        """Inject a smart execution that produces a failure
        outcome and verify the aggregated insights list
        contains a failure entry with root_cause +
        recommendation."""
        ac = self._make_controller(tmp_path)

        import execution.smart_executor as se_mod

        class _SE:
            def execute_batch(self, actions, store_data=None):
                return {
                    "total": 1, "simulated": 1, "dry_run": 0, "live": 0,
                    "avg_score": 1.0,
                    "results": [{
                        "action_type": "fake_fail",
                        "mode": "simulate",
                        "score": 1.0,
                        "duration_s": 0.01,
                        "actual_outcome": {
                            "status": "error",
                            "error": "timeout while fetching",
                        },
                    }],
                }

        monkeypatch.setattr(se_mod, "get_smart_executor", lambda: _SE())
        ac._action_executor._pending_actions = [
            {"type": "fake_fail", "confidence": 0.5},
        ]

        result = ac.run_cycle("r_test")
        learning = result["phases"].get("learning", {})
        insights = learning.get("brain_insights", [])
        # Should have at least one failure insight
        failure_entries = [
            i for i in insights if i.get("type") == "failure"
        ]
        assert failure_entries, (
            f"expected at least one failure insight; "
            f"got brain_insights={insights}"
        )
        entry = failure_entries[0]
        assert "root_cause" in entry
        assert "recommendation" in entry
        assert "action" in entry
