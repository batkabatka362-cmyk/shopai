"""MCTS planner tests — legality, rollouts, determinism, ranking."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import tree_search as ts
from core.brain.world_model import Context, WorldModel


class TestLegalActions(unittest.TestCase):
    def test_no_launches_blocks_scale_kill(self) -> None:
        s = ts.State(open_launches=0, cash_band="mid")
        legal = ts._legal_actions(s)
        self.assertNotIn("scale", legal)
        self.assertNotIn("kill", legal)
        self.assertIn("launch", legal)

    def test_low_cash_blocks_launch(self) -> None:
        s = ts.State(open_launches=1, cash_band="low")
        legal = ts._legal_actions(s)
        self.assertNotIn("launch", legal)
        self.assertIn("kill", legal)

    def test_always_at_least_wait(self) -> None:
        s = ts.State(open_launches=0, cash_band="low")
        legal = ts._legal_actions(s)
        self.assertIn("wait", legal)


class TestTransitions(unittest.TestCase):
    def test_launch_increments_open(self) -> None:
        s = ts.State(open_launches=1)
        s2 = ts._apply_action(s, "launch")
        self.assertEqual(s2.open_launches, 2)
        self.assertEqual(s2.days_elapsed, 1)

    def test_kill_decrements_and_clamps(self) -> None:
        s = ts.State(open_launches=0)
        s2 = ts._apply_action(s, "kill")
        self.assertEqual(s2.open_launches, 0)

    def test_wait_skips_three_days(self) -> None:
        s = ts.State()
        s2 = ts._apply_action(s, "wait")
        self.assertEqual(s2.days_elapsed, 3)


class TestPlannerShape(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wm = WorldModel(Path(self._tmp.name) / "w.db")
        self.planner = ts.MCTSPlanner(wm=self.wm, seed=7, rollout_depth=3)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_plan_returns_trace_with_best_action(self) -> None:
        root = ts.State(open_launches=1, cash_band="mid",
                        niche="audio")
        trace = self.planner.plan(root, simulations=30,
                                  time_budget_s=2.0)
        self.assertGreater(trace.simulations, 0)
        self.assertIn(trace.best_action,
                      [b.action for b in trace.branches])

    def test_plan_under_time_budget(self) -> None:
        root = ts.State(open_launches=1)
        trace = self.planner.plan(root, simulations=5000,
                                  time_budget_s=0.2)
        self.assertLess(trace.elapsed_s, 0.5)


class TestPlannerUsesWorldModel(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.wm = WorldModel(Path(self._tmp.name) / "w.db")
        # Populate so 'scale' looks dramatically better than 'kill'
        # under audio/mid/high/luxury. Coarsenings ensure niche-only
        # query still matches even if context drifts.
        ctx = Context(niche="audio", price_band="mid",
                      margin_band="high", copy_tone="luxury")
        for v in (5.0, 5.2, 5.1, 4.9, 5.3):
            self.wm.update(ctx, "scale", "roas", v)
        for v in (0.2, 0.1, 0.3, 0.2, 0.15):
            self.wm.update(ctx, "kill", "roas", v)
        # Bias other actions low so they don't win by chance
        for a in ("hold", "wait", "add_cross_sell"):
            for v in (0.3, 0.4, 0.35):
                self.wm.update(ctx, a, "roas", v)
        self.planner = ts.MCTSPlanner(wm=self.wm, seed=42,
                                      rollout_depth=2)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_picks_scale_when_scale_is_strongly_best(self) -> None:
        root = ts.State(open_launches=2, cash_band="mid",
                        niche="audio", price_band="mid",
                        margin_band="high", copy_tone="luxury")
        trace = self.planner.plan(root, simulations=200,
                                  time_budget_s=2.0)
        # Scale should rank at least in top 2 choices
        top_two = [b.action for b in trace.branches[:2]]
        self.assertIn("scale", top_two)


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_best_action(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        wm = WorldModel(Path(tmp.name) / "w.db")
        p1 = ts.MCTSPlanner(wm=wm, seed=99, rollout_depth=3)
        p2 = ts.MCTSPlanner(wm=wm, seed=99, rollout_depth=3)
        root = ts.State(open_launches=1, niche="z")
        t1 = p1.plan(root, simulations=50, time_budget_s=2.0)
        t2 = p2.plan(root, simulations=50, time_budget_s=2.0)
        # Rollout bootstrap RNG drives branch order when WM is empty.
        self.assertEqual(t1.best_action, t2.best_action)
        tmp.cleanup()


class TestNoLegalMoves(unittest.TestCase):
    def test_defaults_to_wait_when_no_sims_run(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        wm = WorldModel(Path(tmp.name) / "w.db")
        planner = ts.MCTSPlanner(wm=wm, seed=1, rollout_depth=1)
        root = ts.State()
        trace = planner.plan(root, simulations=0, time_budget_s=0.0)
        self.assertEqual(trace.best_action, "wait")
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
