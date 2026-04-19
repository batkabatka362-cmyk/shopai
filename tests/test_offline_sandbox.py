"""Offline sandbox — deterministic plan simulation tests."""
from __future__ import annotations

import unittest

from core.brain import offline_sandbox as osb


class TestSimLaunch(unittest.TestCase):
    def test_active_launch_earns(self) -> None:
        import random
        launch = osb.SimLaunch(launch_id="x", daily_budget=20, roas=3)
        rng = random.Random(0)
        spend, revenue = launch.step_one_day(rng)
        self.assertEqual(spend, 20)
        self.assertGreater(revenue, 0)
        self.assertEqual(launch.days_live, 1)

    def test_killed_launch_earns_zero(self) -> None:
        launch = osb.SimLaunch(launch_id="x", status="killed")
        spend, revenue = launch.step_one_day(__import__("random"))
        self.assertEqual((spend, revenue), (0.0, 0.0))


class TestApplyAction(unittest.TestCase):
    def setUp(self) -> None:
        self.world = osb.SimWorld(seed=1)

    def test_launch_product_seeds_launch(self) -> None:
        self.world.apply_action({
            "id": "n1", "params": {
                "kind": "launch_product", "ad_budget_day": 50,
                "niche": "audio",
            },
        })
        self.assertEqual(len(self.world.launches), 1)
        launch = next(iter(self.world.launches.values()))
        self.assertEqual(launch.daily_budget, 50)
        self.assertEqual(launch.niche, "audio")

    def test_scale_doubles_budget(self) -> None:
        launch = self.world.seed_launch("s1", daily_budget=20)
        self.world.apply_action({
            "id": "n2",
            "params": {"kind": "scale_launch",
                       "launch_id": "s1", "scale_factor": 2.5},
        })
        self.assertEqual(launch.daily_budget, 50.0)
        self.assertEqual(launch.status, "scaled")

    def test_kill_marks_status(self) -> None:
        self.world.seed_launch("k1")
        self.world.apply_action({
            "id": "n3",
            "params": {"kind": "kill_launch", "launch_id": "k1"},
        })
        self.assertEqual(self.world.launches["k1"].status, "killed")
        self.assertIn("k1", self.world.killed)

    def test_wait_ticks(self) -> None:
        self.world.seed_launch("w1")
        self.world.apply_action({
            "id": "n4",
            "params": {"kind": "wait", "days": 2},
        })
        self.assertEqual(self.world.ticks, 2)

    def test_cross_sell_lifts_aov(self) -> None:
        launch = self.world.seed_launch("c1")
        launch.aov = 100
        self.world.apply_action({
            "id": "n5",
            "params": {"kind": "add_cross_sell"},
        })
        self.assertAlmostEqual(launch.aov, 107.0, places=2)


class TestRunPlan(unittest.TestCase):
    def test_launch_then_kill_produces_report(self) -> None:
        nodes = [
            {"id": "a", "params": {"kind": "launch_product",
                                    "ad_budget_day": 20, "niche": "x"}},
            {"id": "b", "params": {"kind": "wait", "days": 3}},
        ]
        report = osb.SimWorld(seed=1).run_plan(nodes)
        self.assertGreater(report.projected_revenue, 0)
        self.assertEqual(report.active_at_end, 1)

    def test_simulate_plan_helper(self) -> None:
        plan = {
            "nodes": [
                {"id": "a", "params": {"kind": "launch_product"}},
                {"id": "b", "params": {"kind": "wait", "days": 3}},
            ],
        }
        r = osb.simulate_plan(plan, seed=2)
        self.assertGreater(r.projected_spend, 0)
        self.assertIn("steps", r.as_dict())


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_result(self) -> None:
        nodes = [
            {"id": "a", "params": {"kind": "launch_product",
                                    "ad_budget_day": 20}},
            {"id": "b", "params": {"kind": "wait", "days": 5}},
        ]
        r1 = osb.SimWorld(seed=99).run_plan(nodes)
        r2 = osb.SimWorld(seed=99).run_plan(nodes)
        self.assertAlmostEqual(r1.projected_revenue, r2.projected_revenue)


if __name__ == "__main__":
    unittest.main()
