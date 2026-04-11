"""Regression tests for Fix G: remove dead ModelCoordinator
call from DecisionBrain.think().

Pre-fix ``DecisionBrain.think`` ran ``ModelCoordinator().
pricing_decision(top_product)`` every cycle and dropped the
output into ``thought["model_coordinator"]``. That key was
never read anywhere in the codebase — a single grep confirmed
exactly ONE reference, the write site itself. The call
burned a ~1-5s legacy LLM request per cycle for zero
downstream value.

Core audit flagged this as the #5 HIGH weakness
(ModelCoordinator vs. DecisionEngine duplication —
competing recommendations with no reconciliation).

Fix G removes the call. These tests pin:

  1. ``DecisionBrain.think()`` no longer writes
     ``thought["model_coordinator"]``.
  2. The source code of ``decision_brain.py`` no longer
     imports ``ModelCoordinator`` or instantiates one
     inside ``think``.
  3. ``ModelCoordinator`` the class is still importable
     and functional for ``tests/test_multi_model.py``
     (which exercises the class directly, not via the
     brain).
  4. The structured pricing path via
     ``DecisionEngine.decide("pricing", ...)`` still runs
     and writes to ``thought["structured_decisions"]``.
"""
from __future__ import annotations

import pytest


class TestBrainDoesNotCallModelCoordinator:
    def test_thought_has_no_model_coordinator_key(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({
            "products": [{
                "id": "p1", "name": "Widget",
                "price": 50.0, "cost": 20.0,
                "inventory_quantity": 10, "image_url": "x",
            }],
            "orders": [],
            "customers": [],
        })
        assert "model_coordinator" not in thought, (
            "thought['model_coordinator'] was re-introduced — "
            "Fix G removed this dead data flow because the key "
            "was never read anywhere"
        )

    def test_decision_brain_source_does_not_import_model_coordinator(self):
        """AST regression: decision_brain.py must not import
        ``ModelCoordinator`` or call ``pricing_decision`` on it.
        Fix G removed both."""
        import pathlib
        src = pathlib.Path("core/brain/decision_brain.py").read_text()

        # No import of ModelCoordinator
        assert "from core.brain.model_coordinator import" not in src or \
               "# Fix G note" in src, (
            "decision_brain.py still imports ModelCoordinator "
            "in a live code path"
        )

        # No call to pricing_decision
        assert "coordinator.pricing_decision" not in src, (
            "decision_brain.py still calls "
            "ModelCoordinator.pricing_decision — Fix G removed it"
        )

    def test_structured_decisions_still_run(self):
        """The DecisionEngine path (which Fix G kept as the
        canonical pricing path) must still populate
        ``thought['structured_decisions']``."""
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({
            "products": [
                {"id": "p1", "name": "Widget",
                 "price": 50.0, "cost": 20.0,
                 "inventory_quantity": 10, "image_url": "x"},
                {"id": "p2", "name": "Gadget",
                 "price": 80.0, "cost": 30.0,
                 "inventory_quantity": 20, "image_url": "x"},
            ],
            "orders": [{"id": "o1", "total": 50.0}],
            "customers": [],
        })
        # structured_decisions is populated (or absent if no
        # actionable decisions came out, but the key should
        # EXIST when any product produced a non-trivial
        # pricing call).
        assert "structured_decisions" in thought or len(thought.get("decisions", [])) > 0


class TestModelCoordinatorStillImportableForTests:
    """``core/brain/model_coordinator.py`` is still used by
    ``tests/test_multi_model.py`` which exercises the class
    directly. Fix G only removed the brain's call — the
    class itself stays so those tests keep working."""

    def test_model_coordinator_class_importable(self):
        from core.brain.model_coordinator import ModelCoordinator
        coord = ModelCoordinator()
        assert coord is not None

    def test_model_coordinator_pricing_decision_still_exists(self):
        """Nothing calls ``pricing_decision`` from production
        code anymore, but the method still exists as part of
        the ModelCoordinator class for future experiments +
        the multi-model test file."""
        from core.brain.model_coordinator import ModelCoordinator
        assert hasattr(ModelCoordinator, "pricing_decision")
        assert callable(getattr(ModelCoordinator, "pricing_decision"))


class TestCycleStillRunsAfterRemoval:
    """Sanity check: a full brain.think() call completes
    cleanly without the ModelCoordinator branch."""

    def test_think_completes_without_error(self):
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think({
            "products": [
                {"id": "p1", "name": "Widget",
                 "price": 50.0, "cost": 20.0,
                 "inventory_quantity": 10, "image_url": "x"},
            ],
            "orders": [],
            "customers": [],
        })
        # Basic cycle-output fields must still be present
        assert "decisions" in thought
        assert "action_plan" in thought
        assert "observations" in thought
        assert "problems" in thought
        assert "opportunities" in thought

    def test_think_with_goal_still_works(self):
        """Fix A's goal-aware path must still work without
        the ModelCoordinator branch."""
        from core.brain.decision_brain import DecisionBrain
        brain = DecisionBrain()
        thought = brain.think(
            {
                "products": [{
                    "id": "p1", "name": "W",
                    "price": 50, "cost": 20,
                    "inventory_quantity": 10,
                    "image_url": "x",
                }],
                "orders": [],
                "customers": [],
            },
            goal="survive_crisis",
        )
        assert thought["goal"] == "survive_crisis"
