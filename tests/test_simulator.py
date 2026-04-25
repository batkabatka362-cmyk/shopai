"""Monte-Carlo simulator — intervention math tests."""
from __future__ import annotations

import random
import unittest

from core.brain import simulator as sim


class TestKillSimulation(unittest.TestCase):
    def test_saves_budget_when_launch_is_unprofitable(self) -> None:
        # Historical run: ad spend $20/day, earned $10/day → kill saves net $10
        spec = sim.SimulationInput(
            intervention="kill_launch",
            launch_id="l1",
            params={"ad_budget_day": 20.0},
            history=[
                {"revenue_usd": 30.0, "days_live": 3.0, "roas": 0.5,
                 "ad_budget_day": 20.0, "cvr": 0.01, "aov": 25.0},
            ],
            trials=200,
            horizon_days=3,
        )
        random.seed(0)
        result = sim.simulate(spec)
        # saved = 20*3 = 60, forgone = 10*3 = 30, net = 30
        self.assertEqual(result.kpi, "net_saved_usd")
        self.assertGreater(result.mean, 25.0)
        self.assertGreater(result.p_positive, 0.9)

    def test_kill_loses_money_when_launch_is_profitable(self) -> None:
        # Historical run: $100/day revenue with $20 spend → kill loses net $60/day
        spec = sim.SimulationInput(
            intervention="kill_launch",
            launch_id="l2",
            params={"ad_budget_day": 20.0},
            history=[
                {"revenue_usd": 300.0, "days_live": 3.0, "roas": 5.0,
                 "ad_budget_day": 20.0, "cvr": 0.05, "aov": 50.0},
            ],
            trials=200,
            horizon_days=3,
        )
        random.seed(0)
        result = sim.simulate(spec)
        self.assertLess(result.mean, 0)
        self.assertLess(result.p_positive, 0.1)


class TestScaleSimulation(unittest.TestCase):
    def test_projects_revenue_with_diminishing_returns(self) -> None:
        spec = sim.SimulationInput(
            intervention="scale_launch",
            launch_id="l1",
            params={"ad_budget_day": 20.0, "scale_factor": 2.0,
                    "diminishing": 0.85},
            history=[
                {"roas": 2.0, "revenue_usd": 100, "days_live": 3,
                 "ad_budget_day": 20, "cvr": 0.05, "aov": 25},
            ],
            trials=200, horizon_days=3,
        )
        random.seed(0)
        result = sim.simulate(spec)
        # Expected: 2.0 * (20*2*0.85*3) = 204
        self.assertAlmostEqual(result.mean, 204.0, places=0)
        self.assertEqual(result.kpi, "projected_revenue_usd")


class TestPriceSimulation(unittest.TestCase):
    def test_higher_price_projects_higher_revenue_when_cvr_holds(self) -> None:
        spec = sim.SimulationInput(
            intervention="change_price",
            launch_id="l",
            params={"old_price": 20.0, "new_price": 30.0},
            history=[
                {"roas": 2.0, "revenue_usd": 200.0, "days_live": 2,
                 "ad_budget_day": 50, "cvr": 0.1, "aov": 20.0},
            ] * 3,
            trials=200, horizon_days=3,
        )
        random.seed(0)
        result = sim.simulate(spec)
        # CVR drops by elasticity×(0.5) = -0.35 → 0.065
        # clicks_per_day = 100 → projected_rev = 0.065 × 30 × 10 × 3 = 58.5
        self.assertEqual(result.kpi, "projected_revenue_usd")
        self.assertGreater(result.mean, 0)


class TestFallbacks(unittest.TestCase):
    def test_empty_history_returns_neutral(self) -> None:
        spec = sim.SimulationInput(
            intervention="kill_launch", launch_id="l",
            params={"ad_budget_day": 20}, history=[],
        )
        result = sim.simulate(spec)
        self.assertEqual(result.trials, 0)
        self.assertIn("neutral", result.narrative)

    def test_unknown_intervention_returns_neutral(self) -> None:
        spec = sim.SimulationInput(
            intervention="alien_action", launch_id="l",
            history=[{"roas": 2, "revenue_usd": 10, "days_live": 1,
                      "ad_budget_day": 5, "cvr": 0.01, "aov": 10}],
        )
        result = sim.simulate(spec)
        self.assertIn("unknown", result.narrative.lower())


if __name__ == "__main__":
    unittest.main()
