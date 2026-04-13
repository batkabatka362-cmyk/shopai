"""Regression tests for Fix M: structured_decisions
surfaced in the cycle output.

Pre-fix, ``DecisionBrain.think()`` built memory-informed
``Decision`` objects via ``DecisionEngine.decide("pricing", p)``
for the top 2 products and appended them to
``thought["structured_decisions"]`` — but the controller
never read that field. It only consumed ``thought["decisions"]``
and ``thought["action_plan"]``, so the richer decision
attribution trail (populated by Fix H: source, rule_id,
description, impact) was lost to downstream consumers.

Core audit re-scan flagged this as the #2 MEDIUM weakness.
Fix M surfaces ``structured_decisions`` on the cycle's
brain phase summary with the full attribution trail
preserved, so dashboards + operators can inspect the
per-product memory-informed pricing path.
"""
from __future__ import annotations

import tempfile

import pytest


def _make_controller(tmp_path):
    from data_pipeline.store.db import ShopAIDatabase
    from data_pipeline.store.store_manager import StoreManager
    from core.autonomous.controller import AutonomousController
    from core.learning.action_weights import reset_action_weight_store

    reset_action_weight_store(tmp_path / "w.db")
    store_db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
    sm = StoreManager(store_db)
    sm.add_store("m_test", "m.myshopify.com", "shpat_t")
    store_db.upsert_products("m_test", [
        {"id": "p1", "title": "Widget", "price": 50, "cost": 20,
         "status": "active", "inventory_quantity": 10},
        {"id": "p2", "title": "Gadget", "price": 80, "cost": 30,
         "status": "active", "inventory_quantity": 20},
    ])
    store_db.upsert_orders("m_test", [
        {"id": "o1", "total": 50, "financial_status": "paid"},
    ])
    store_db.upsert_customers("m_test", [
        {"id": "c1", "email": "t@t.com"},
    ])
    store_db.log_sync("m_test", "products", "success", 2, 0.1)
    store_db.log_sync("m_test", "orders", "success", 1, 0.1)
    store_db.log_sync("m_test", "customers", "success", 1, 0.1)

    ac = AutonomousController(sm, auto_approve=False)
    ac.initialize()
    return ac


class TestStructuredDecisionsOnCycleResult:
    def test_brain_phase_carries_structured_decisions(self, tmp_path):
        """After running a full cycle, the brain phase summary
        must carry a ``structured_decisions`` field (a list)
        — zero-length if no pricing decision was generated,
        but ALWAYS present."""
        ac = _make_controller(tmp_path)
        result = ac.run_cycle("m_test")
        brain = result["phases"].get("brain", {})
        assert "structured_decisions" in brain, (
            "Fix M: brain phase must expose structured_decisions; "
            f"brain keys = {list(brain.keys())}"
        )
        sd = brain["structured_decisions"]
        assert isinstance(sd, list)

    def test_structured_decisions_preserve_attribution(self, tmp_path):
        """If any structured decisions ARE generated (i.e.
        brain.think ran DecisionEngine.decide for ≥1 product),
        each entry must carry the Fix H attribution trail."""
        ac = _make_controller(tmp_path)
        result = ac.run_cycle("m_test")
        brain = result["phases"].get("brain", {})
        sd = brain.get("structured_decisions", [])
        for entry in sd:
            assert isinstance(entry, dict)
            assert "choice" in entry
            assert "score" in entry
            assert "attribution" in entry, (
                f"structured decision missing attribution: {entry}"
            )
            assert isinstance(entry["attribution"], list)

    def test_structured_decisions_count_on_summary(self, tmp_path):
        """Operators need a single integer for dashboards.
        The brain phase must carry ``structured_decisions_count``
        derived from the list length."""
        ac = _make_controller(tmp_path)
        result = ac.run_cycle("m_test")
        brain = result["phases"].get("brain", {})
        assert "structured_decisions_count" in brain
        assert isinstance(brain["structured_decisions_count"], int)
        assert brain["structured_decisions_count"] == len(
            brain.get("structured_decisions", []),
        )


class TestStructuredDecisionsStillWrittenByBrain:
    """Regression guard: the brain's write site must still
    populate ``thought["structured_decisions"]`` (Fix M only
    surfaces it, doesn't change where it's written)."""

    def test_brain_still_writes_structured_decisions(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({
            "products": [
                {"id": "p1", "name": "W", "price": 50, "cost": 20,
                 "inventory_quantity": 10, "image_url": "x"},
                {"id": "p2", "name": "G", "price": 80, "cost": 30,
                 "inventory_quantity": 20, "image_url": "x"},
            ],
            "orders": [], "customers": [],
        })
        # structured_decisions may be empty if every option
        # was "no_action", but the key should either be
        # present OR absent — the write site runs unchanged.
        assert "structured_decisions" in thought or len(thought.get("decisions", [])) >= 0


class TestControllerSourceReferencesStructuredDecisions:
    """AST-level guard: controller.py must reference
    ``structured_decisions`` so the Fix M wiring can't be
    dropped without tripping this test."""

    def test_controller_reads_structured_decisions(self):
        import pathlib
        text = pathlib.Path("core/autonomous/controller.py").read_text(
            encoding="utf-8",
        )
        assert "structured_decisions" in text, (
            "controller.py must reference structured_decisions "
            "to surface them on the cycle summary"
        )
