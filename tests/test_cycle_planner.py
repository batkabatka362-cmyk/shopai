"""Cycle planner tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import cycle_planner as cp


class TestBudgetMode(unittest.TestCase):
    def test_conservative_when_failure_rate_high(self) -> None:
        mode, reasons = cp._decide_budget_mode(
            llm_stats={"total_calls": 20, "failures": 6},
            learning_trend={"trend": "plateau"},
            weak=[],
        )
        self.assertEqual(mode, "conservative")
        self.assertTrue(any("LLM failure" in r for r in reasons))

    def test_conservative_when_regressing(self) -> None:
        mode, _ = cp._decide_budget_mode(
            llm_stats={"total_calls": 5, "failures": 0},
            learning_trend={"trend": "regressing"},
            weak=[],
        )
        self.assertEqual(mode, "conservative")

    def test_aggressive_when_clear_skies(self) -> None:
        mode, _ = cp._decide_budget_mode(
            llm_stats={"total_calls": 20, "failures": 0},
            learning_trend={"trend": "improving"},
            weak=[],
        )
        self.assertEqual(mode, "aggressive")

    def test_normal_default(self) -> None:
        mode, _ = cp._decide_budget_mode(
            llm_stats={"total_calls": 5, "failures": 0},
            learning_trend={"trend": "plateau"},
            weak=["x"],
        )
        self.assertEqual(mode, "normal")


class TestPlanNextCycle(unittest.TestCase):
    def test_empty_state_returns_neutral_plan(self) -> None:
        with patch.object(cp, "_recent_phase_errors", return_value={}), \
             patch.object(cp, "_weak_subsystems", return_value=[]), \
             patch.object(cp, "_drifted_features", return_value=[]), \
             patch.object(cp, "_pending_commitments", return_value=[]), \
             patch.object(cp, "_curiosity_topk", return_value=[]), \
             patch.object(
                cp, "_llm_spend",
                return_value={"total_calls": 0, "failures": 0},
             ), \
             patch.object(
                cp, "_learning_trend",
                return_value={"trend": "insufficient"},
             ), \
             patch.object(cp, "_mirror_plan"):
            plan = cp.plan_next_cycle(cycle_id="c1")
        self.assertEqual(plan.cycle_id, "c1")
        self.assertEqual(plan.focus_areas, [])
        self.assertEqual(plan.avoid_areas, [])
        self.assertEqual(plan.budget_mode, "normal")
        self.assertIn("phase_error_count", plan.suggested_kpis)

    def test_drift_drives_focus(self) -> None:
        with patch.object(cp, "_recent_phase_errors", return_value={}), \
             patch.object(cp, "_weak_subsystems", return_value=[]), \
             patch.object(
                cp, "_drifted_features", return_value=["cpm", "cvr"],
             ), \
             patch.object(cp, "_pending_commitments", return_value=[]), \
             patch.object(cp, "_curiosity_topk", return_value=[]), \
             patch.object(
                cp, "_llm_spend",
                return_value={"total_calls": 0, "failures": 0},
             ), \
             patch.object(
                cp, "_learning_trend",
                return_value={"trend": "plateau"},
             ), \
             patch.object(cp, "_mirror_plan"):
            plan = cp.plan_next_cycle()
        self.assertTrue(any("drift:cpm" in f for f in plan.focus_areas))
        self.assertIn("cpm", plan.suggested_kpis)

    def test_repeat_phase_errors_go_to_avoid(self) -> None:
        with patch.object(
                cp, "_recent_phase_errors",
                return_value={"fetch": 5, "parse": 1},
             ), \
             patch.object(cp, "_weak_subsystems", return_value=[]), \
             patch.object(cp, "_drifted_features", return_value=[]), \
             patch.object(cp, "_pending_commitments", return_value=[]), \
             patch.object(cp, "_curiosity_topk", return_value=[]), \
             patch.object(
                cp, "_llm_spend",
                return_value={"total_calls": 0, "failures": 0},
             ), \
             patch.object(
                cp, "_learning_trend",
                return_value={"trend": "plateau"},
             ), \
             patch.object(cp, "_mirror_plan"):
            plan = cp.plan_next_cycle()
        # fetch has ≥3 errors → avoid; parse has 1 → not
        self.assertIn("phase:fetch", plan.avoid_areas)
        self.assertNotIn("phase:parse", plan.avoid_areas)

    def test_weak_subsystems_listed(self) -> None:
        with patch.object(cp, "_recent_phase_errors", return_value={}), \
             patch.object(
                cp, "_weak_subsystems",
                return_value=["pricing_engine", "attribution"],
             ), \
             patch.object(cp, "_drifted_features", return_value=[]), \
             patch.object(cp, "_pending_commitments", return_value=[]), \
             patch.object(cp, "_curiosity_topk", return_value=[]), \
             patch.object(
                cp, "_llm_spend",
                return_value={"total_calls": 0, "failures": 0},
             ), \
             patch.object(
                cp, "_learning_trend",
                return_value={"trend": "plateau"},
             ), \
             patch.object(cp, "_mirror_plan"):
            plan = cp.plan_next_cycle()
        self.assertIn("weak:pricing_engine", plan.avoid_areas)

    def test_urgent_commitments_in_retry(self) -> None:
        with patch.object(cp, "_recent_phase_errors", return_value={}), \
             patch.object(cp, "_weak_subsystems", return_value=[]), \
             patch.object(cp, "_drifted_features", return_value=[]), \
             patch.object(
                cp, "_pending_commitments",
                return_value=[{"id": "c1"}, {"id": "c2"}],
             ), \
             patch.object(cp, "_curiosity_topk", return_value=[]), \
             patch.object(
                cp, "_llm_spend",
                return_value={"total_calls": 0, "failures": 0},
             ), \
             patch.object(
                cp, "_learning_trend",
                return_value={"trend": "plateau"},
             ), \
             patch.object(cp, "_mirror_plan"):
            plan = cp.plan_next_cycle()
        kinds = [r["type"] for r in plan.retry_items]
        self.assertIn("commitment", kinds)

    def test_retry_capped_at_ten(self) -> None:
        many = [{"id": f"c{i}"} for i in range(30)]
        with patch.object(cp, "_recent_phase_errors", return_value={}), \
             patch.object(cp, "_weak_subsystems", return_value=[]), \
             patch.object(cp, "_drifted_features", return_value=[]), \
             patch.object(cp, "_pending_commitments", return_value=many), \
             patch.object(cp, "_curiosity_topk", return_value=[]), \
             patch.object(
                cp, "_llm_spend",
                return_value={"total_calls": 0, "failures": 0},
             ), \
             patch.object(
                cp, "_learning_trend",
                return_value={"trend": "plateau"},
             ), \
             patch.object(cp, "_mirror_plan"):
            plan = cp.plan_next_cycle()
        self.assertLessEqual(len(plan.retry_items), 10)


class TestDict(unittest.TestCase):
    def test_plan_as_dict(self) -> None:
        p = cp.CyclePlan(cycle_id="x", budget_mode="normal")
        d = p.as_dict()
        self.assertEqual(d["cycle_id"], "x")
        self.assertEqual(d["budget_mode"], "normal")


class TestRender(unittest.TestCase):
    def test_render_plan_md(self) -> None:
        p = cp.CyclePlan(
            cycle_id="c",
            focus_areas=["drift:cpm"],
            avoid_areas=["phase:fetch"],
            retry_items=[{"type": "commitment", "ref": "c1"}],
            suggested_kpis=["roas"],
            budget_mode="normal",
            rationale=["test"],
        )
        body = cp._render_plan_md(p)
        self.assertIn("drift:cpm", body)
        self.assertIn("phase:fetch", body)
        self.assertIn("roas", body)


if __name__ == "__main__":
    unittest.main()
