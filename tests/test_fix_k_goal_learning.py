"""Regression tests for Fix K: GoalManager learns from
cycle outcomes.

Pre-fix, ``GoalManager.select_goal()`` was deterministic
rule-based (``health_grade``, ``churn_pct``, seasonal
checks) with no feedback mechanism. If the store selected
``grow_customers`` ten cycles in a row and every cycle
saw churn GET WORSE, the next cycle would still pick
``grow_customers`` with the same 0.85 confidence — the
manager had no memory of what had happened before.

Core audit re-scan flagged this as the #3 HIGH weakness
("GoalManager never learns from outcomes"). Fix K adds:

  1. ``record_goal_outcome(goal, metrics)`` — updates a
     per-goal EMA of success based on profit/revenue/health
     deltas observed after running under that goal.
  2. ``get_effectiveness(goal)`` — read the current EMA.
  3. ``get_effectiveness_stats()`` — bulk inspection for
     operators + tests.
  4. ``_evaluate_goals`` now reads the effectiveness table
     and applies it as a priority adjustment (±0.5) and a
     confidence multiplier so historically-successful goals
     rise in the ranking and persistently-failing ones fall.
  5. ``AutonomousController.run_cycle`` phase 5 calls
     ``record_goal_outcome`` with the cycle's
     ``avg_exec_score``-based delta signal — closing the
     selected-goal → run → outcome → next selection loop.
"""
from __future__ import annotations

import pytest


class TestRecordGoalOutcomeAPI:
    def test_record_goal_outcome_method_exists(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        assert hasattr(gm, "record_goal_outcome")
        assert callable(gm.record_goal_outcome)

    def test_effectiveness_starts_at_neutral(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        eff = gm.get_effectiveness("maximize_profit")
        assert 0.4 <= eff <= 0.6, f"neutral should be ~0.5, got {eff}"

    def test_positive_outcome_raises_effectiveness(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        start = gm.get_effectiveness("maximize_profit")
        for _ in range(5):
            gm.record_goal_outcome("maximize_profit", {
                "profit_delta": 100, "revenue_delta": 500, "health_delta": 5,
            })
        end = gm.get_effectiveness("maximize_profit")
        assert end > start, (
            f"5 positive outcomes should raise effectiveness "
            f"(start={start}, end={end})"
        )

    def test_negative_outcome_lowers_effectiveness(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        start = gm.get_effectiveness("grow_customers")
        for _ in range(5):
            gm.record_goal_outcome("grow_customers", {
                "profit_delta": -50, "revenue_delta": -200, "health_delta": -3,
            })
        end = gm.get_effectiveness("grow_customers")
        assert end < start, (
            f"5 negative outcomes should lower effectiveness "
            f"(start={start}, end={end})"
        )

    def test_effectiveness_bounded_0_to_1(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        for _ in range(50):
            gm.record_goal_outcome("increase_aov", {
                "profit_delta": 999, "revenue_delta": 999, "health_delta": 99,
            })
        assert gm.get_effectiveness("increase_aov") <= 1.0
        for _ in range(50):
            gm.record_goal_outcome("increase_aov", {
                "profit_delta": -999, "revenue_delta": -999, "health_delta": -99,
            })
        assert gm.get_effectiveness("increase_aov") >= 0.0

    def test_get_effectiveness_stats_returns_all_recorded(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        gm.record_goal_outcome("maximize_profit", {"profit_delta": 10})
        gm.record_goal_outcome("grow_customers", {"profit_delta": -5})
        stats = gm.get_effectiveness_stats()
        assert "maximize_profit" in stats
        assert "grow_customers" in stats
        assert stats["maximize_profit"]["n"] == 1
        assert stats["grow_customers"]["n"] == 1


class TestGoalSelectionUsesEffectiveness:
    """The rule-based selection must now consult the
    effectiveness table and adjust priorities + confidence."""

    def test_high_effectiveness_boosts_confidence(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        # Baseline: neutral effectiveness
        baseline = gm.select_goal({"financial": {"health_grade": "B"}})
        baseline_conf = baseline["confidence"]

        # Force a high effectiveness for the default goal
        for _ in range(20):
            gm.record_goal_outcome("maximize_profit", {
                "profit_delta": 100, "revenue_delta": 500, "health_delta": 5,
            })
        boosted = gm.select_goal({"financial": {"health_grade": "B"}})
        # Confidence should have moved; we accept either
        # direction (boosted OR baseline) depending on the
        # multiplier sign, but the VALUES should differ.
        assert boosted["confidence"] != baseline_conf, (
            f"effectiveness should affect confidence "
            f"(baseline={baseline_conf}, boosted={boosted['confidence']})"
        )
        # Specifically: high effectiveness should boost
        assert boosted["confidence"] > baseline_conf, (
            "high effectiveness should boost confidence"
        )

    def test_effectiveness_surfaces_on_selection_result(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        gm.record_goal_outcome("maximize_profit", {"profit_delta": 10})
        result = gm.select_goal({"financial": {"health_grade": "B"}})
        assert "effectiveness" in result

    def test_crisis_goal_cannot_be_overridden_by_low_effectiveness(self):
        """Even if survive_crisis has 0 historical effectiveness,
        a D-grade situation must still select it — safety
        rules are sacrosanct."""
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        # Tank survive_crisis effectiveness
        for _ in range(30):
            gm.record_goal_outcome("survive_crisis", {
                "profit_delta": -500, "revenue_delta": -1000, "health_delta": -10,
            })
        result = gm.select_goal({
            "financial": {"health_grade": "D", "critical_alerts": 3},
        }, cycle_number=100)
        assert result["goal"] == "survive_crisis", (
            "crisis trigger must override effectiveness — "
            "health safety rules are absolute"
        )


class TestGoalOutcomeWiredToController:
    """The controller must call ``record_goal_outcome`` at
    phase 5 so effectiveness actually accumulates from real
    cycles, not just from test injection."""

    def test_controller_has_record_goal_outcome_hook(self):
        """AST-level guard: controller.py must reference
        ``record_goal_outcome`` so the Fix K wiring can't be
        silently dropped."""
        import pathlib
        text = pathlib.Path("core/autonomous/controller.py").read_text(
            encoding="utf-8",
        )
        assert "record_goal_outcome" in text, (
            "controller.py must call GoalManager.record_goal_outcome "
            "to close the cycle → outcome → goal learning loop"
        )

    def test_full_cycle_records_goal_outcome(self, tmp_path):
        """Run a full cycle and verify the goal manager's
        effectiveness stats now contain at least one record."""
        from data_pipeline.store.db import ShopAIDatabase
        from data_pipeline.store.store_manager import StoreManager
        from core.autonomous.controller import AutonomousController
        from core.learning.action_weights import reset_action_weight_store

        reset_action_weight_store(tmp_path / "w.db")
        import tempfile
        store_db = ShopAIDatabase(tempfile.mktemp(suffix=".db"))
        sm = StoreManager(store_db)
        sm.add_store("k_test", "k.myshopify.com", "shpat_t")
        store_db.upsert_products("k_test", [
            {"id": "p1", "title": "W", "price": 29.99, "cost": 10,
             "status": "active", "inventory_quantity": 50},
        ])
        store_db.log_sync("k_test", "products", "success", 1, 0.1)

        ac = AutonomousController(sm, auto_approve=False)
        ac.initialize()
        result = ac.run_cycle("k_test")
        assert result.get("status") == "complete"

        # The cycle selected a goal — the goal manager should
        # now have at least one outcome recorded for it
        gm = ac._goal_manager
        stats = gm.get_effectiveness_stats()
        selected_goal = result["phases"].get("goal", {}).get("selected", "")
        if selected_goal:
            assert selected_goal in stats, (
                f"cycle selected {selected_goal} but "
                f"effectiveness stats are {stats}"
            )
            assert stats[selected_goal]["n"] >= 1


class TestGoalEffectivenessStability:
    """EMA semantics: many positive outcomes should converge
    near 1.0, not oscillate."""

    def test_ema_converges_on_steady_positive(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        for _ in range(30):
            gm.record_goal_outcome("capture_opportunity", {
                "profit_delta": 50, "revenue_delta": 100, "health_delta": 2,
            })
        eff = gm.get_effectiveness("capture_opportunity")
        assert eff > 0.9, f"expected near-1.0 after 30 positive, got {eff}"

    def test_ema_converges_on_steady_negative(self):
        from core.goals.goal_manager import GoalManager
        gm = GoalManager()
        for _ in range(30):
            gm.record_goal_outcome("capture_opportunity", {
                "profit_delta": -50, "revenue_delta": -100, "health_delta": -2,
            })
        eff = gm.get_effectiveness("capture_opportunity")
        assert eff < 0.1, f"expected near-0.0 after 30 negative, got {eff}"
