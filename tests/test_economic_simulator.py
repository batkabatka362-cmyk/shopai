"""Economic simulator tests."""
from __future__ import annotations

import random
import unittest

from core.brain import economic_simulator as es


class TestPointProjection(unittest.TestCase):
    def test_profitable_launch_grows_balance(self) -> None:
        launches = [es.LaunchPlan(
            launch_id="L1", daily_spend=20, roas_mean=3.0,
        )]
        proj = es.project(
            launches, costs=es.CostPlan(), starting_balance=100,
            horizon_days=30,
        )
        self.assertGreater(proj.summary.ending_balance,
                            proj.summary.starting_balance)
        self.assertGreater(proj.summary.total_revenue,
                            proj.summary.total_spend)

    def test_unprofitable_launch_hits_runway(self) -> None:
        launches = [es.LaunchPlan(
            launch_id="L1", daily_spend=50, roas_mean=0.5,
        )]
        proj = es.project(
            launches, costs=es.CostPlan(),
            starting_balance=100, horizon_days=30,
        )
        self.assertLess(proj.summary.ending_balance, 100)
        self.assertIsNotNone(proj.summary.runway_days)

    def test_fixed_costs_drain_without_launches(self) -> None:
        proj = es.project(
            launches=[],
            costs=es.CostPlan(monthly_fixed=300),
            starting_balance=1000, horizon_days=30,
        )
        self.assertAlmostEqual(
            proj.summary.ending_balance, 700, places=1,
        )

    def test_days_remaining_ends_launch(self) -> None:
        launches = [
            es.LaunchPlan(
                launch_id="L1", daily_spend=10,
                roas_mean=0.0, days_remaining=5,
            ),
        ]
        proj = es.project(
            launches, costs=es.CostPlan(),
            starting_balance=1000, horizon_days=30,
        )
        # Only 5 days of spend at $10 = $50 total spend
        self.assertAlmostEqual(proj.summary.total_spend, 50, places=1)

    def test_variable_cost_reduces_net_revenue(self) -> None:
        launches = [es.LaunchPlan(
            launch_id="L1", daily_spend=10, roas_mean=2.0,
        )]
        no_cogs = es.project(
            launches, costs=es.CostPlan(),
            starting_balance=0, horizon_days=10,
        )
        with_cogs = es.project(
            launches, costs=es.CostPlan(cogs_pct_of_revenue=0.5),
            starting_balance=0, horizon_days=10,
        )
        self.assertGreater(
            no_cogs.summary.ending_balance,
            with_cogs.summary.ending_balance,
        )

    def test_zero_horizon_raises(self) -> None:
        with self.assertRaises(ValueError):
            es.project([], es.CostPlan(), 100, 0)


class TestMinBalance(unittest.TestCase):
    def test_min_balance_identified(self) -> None:
        proj = es.project(
            launches=[es.LaunchPlan(
                launch_id="L", daily_spend=100, roas_mean=0.1,
            )],
            costs=es.CostPlan(),
            starting_balance=500, horizon_days=10,
        )
        self.assertLess(proj.summary.min_balance, 500)


class TestMonteCarlo(unittest.TestCase):
    def test_percentile_bands(self) -> None:
        launches = [es.LaunchPlan(
            launch_id="L1", daily_spend=20, roas_mean=2.0,
            roas_stdev=0.5,
        )]
        proj = es.project(
            launches, costs=es.CostPlan(),
            starting_balance=100, horizon_days=30,
            mode="monte_carlo", n_samples=50,
            rng=random.Random(42),
        )
        last = proj.daily[-1]
        self.assertIsNotNone(last.p10)
        self.assertIsNotNone(last.p50)
        self.assertIsNotNone(last.p90)
        self.assertLessEqual(last.p10, last.p50)
        self.assertLessEqual(last.p50, last.p90)


class TestSerialise(unittest.TestCase):
    def test_as_dict_covers_summary_and_daily(self) -> None:
        proj = es.project(
            launches=[],
            costs=es.CostPlan(),
            starting_balance=0, horizon_days=3,
        )
        d = proj.as_dict()
        self.assertIn("summary", d)
        self.assertIn("daily", d)
        self.assertEqual(len(d["daily"]), 3)


class TestLaunchHelpers(unittest.TestCase):
    def test_active_on_indefinite(self) -> None:
        l = es.LaunchPlan(
            launch_id="x", daily_spend=1, roas_mean=1,
        )
        self.assertTrue(l.active_on(9999))

    def test_active_on_cuts_off(self) -> None:
        l = es.LaunchPlan(
            launch_id="x", daily_spend=1, roas_mean=1,
            days_remaining=3,
        )
        self.assertTrue(l.active_on(2))
        self.assertFalse(l.active_on(3))
        self.assertFalse(l.active_on(100))


if __name__ == "__main__":
    unittest.main()
