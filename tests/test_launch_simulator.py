"""Tests for simulation.launch_simulator — Monte Carlo safety gate."""
from __future__ import annotations

import unittest

from simulation.launch_simulator import (
    LaunchCandidate,
    LaunchProjection,
    simulate_launch,
)


def _healthy(**overrides):
    """Candidate with a clearly profitable distribution."""
    kw = dict(
        cost=5.0,
        price=30.0,
        daily_budget_usd=20.0,
        days=3,
        est_cvr_mean=0.05,
        est_cvr_stddev=0.005,
        est_cpc_mean=1.0,
        est_cpc_stddev=0.1,
        refund_rate=0.05,
    )
    kw.update(overrides)
    return LaunchCandidate(**kw)


def _losing(**overrides):
    """Candidate with a clearly unprofitable distribution."""
    kw = dict(
        cost=10.0,
        price=12.0,
        daily_budget_usd=50.0,
        days=3,
        est_cvr_mean=0.005,
        est_cvr_stddev=0.001,
        est_cpc_mean=3.0,
        est_cpc_stddev=0.5,
        refund_rate=0.10,
    )
    kw.update(overrides)
    return LaunchCandidate(**kw)


class TestCandidateValidation(unittest.TestCase):
    def test_negative_cost_raises(self):
        with self.assertRaises(ValueError):
            LaunchCandidate(
                cost=-1, price=10, daily_budget_usd=5,
            )

    def test_negative_budget_raises(self):
        with self.assertRaises(ValueError):
            LaunchCandidate(
                cost=1, price=10, daily_budget_usd=-5,
            )

    def test_zero_days_raises(self):
        with self.assertRaises(ValueError):
            LaunchCandidate(
                cost=1, price=10, daily_budget_usd=5, days=0,
            )

    def test_refund_rate_out_of_range(self):
        with self.assertRaises(ValueError):
            LaunchCandidate(
                cost=1, price=10, daily_budget_usd=5,
                refund_rate=1.5,
            )

    def test_margin_ratio(self):
        c = _healthy()
        self.assertAlmostEqual(
            c.margin_ratio(),
            (30 - 5) / 30,
            places=4,
        )


class TestSimulatorDeterminism(unittest.TestCase):
    def test_same_seed_same_result(self):
        c = _healthy()
        a = simulate_launch(c, seed=42)
        b = simulate_launch(c, seed=42)
        self.assertEqual(a.profit_p25, b.profit_p25)
        self.assertEqual(a.profit_p50, b.profit_p50)
        self.assertEqual(a.profit_p75, b.profit_p75)
        self.assertEqual(
            a.break_even_prob, b.break_even_prob,
        )

    def test_different_seeds_differ_slightly(self):
        c = _healthy()
        a = simulate_launch(c, seed=1)
        b = simulate_launch(c, seed=2)
        self.assertNotEqual(a.profit_p50, b.profit_p50)


class TestVerdicts(unittest.TestCase):
    def test_healthy_candidate_is_go(self):
        p = simulate_launch(_healthy(), seed=42)
        self.assertEqual(p.verdict, "go")
        self.assertGreater(p.break_even_prob, 0.6)
        self.assertGreater(p.profit_p50, 0)

    def test_losing_candidate_is_stand_down(self):
        p = simulate_launch(_losing(), seed=42)
        self.assertEqual(p.verdict, "stand_down")
        self.assertLess(p.profit_p50, 0)

    def test_price_below_cost_stand_down(self):
        c = LaunchCandidate(
            cost=10, price=5, daily_budget_usd=10,
        )
        p = simulate_launch(c, seed=42)
        self.assertEqual(p.verdict, "stand_down")
        self.assertIn("price", p.reason)

    def test_caution_between_thresholds(self):
        # Marginal candidate — break-even ~50%
        c = LaunchCandidate(
            cost=10, price=15,
            daily_budget_usd=30, days=3,
            est_cvr_mean=0.03, est_cvr_stddev=0.015,
            est_cpc_mean=2.0, est_cpc_stddev=0.8,
            refund_rate=0.05,
        )
        p = simulate_launch(c, seed=42)
        self.assertIn(p.verdict, ("caution", "stand_down"))


class TestProjectionShape(unittest.TestCase):
    def test_percentile_ordering(self):
        p = simulate_launch(_healthy(), seed=42)
        self.assertLessEqual(p.profit_p25, p.profit_p50)
        self.assertLessEqual(p.profit_p50, p.profit_p75)

    def test_break_even_prob_in_unit(self):
        p = simulate_launch(_healthy(), seed=42)
        self.assertGreaterEqual(p.break_even_prob, 0.0)
        self.assertLessEqual(p.break_even_prob, 1.0)

    def test_expected_roas_positive_for_healthy(self):
        p = simulate_launch(_healthy(), seed=42)
        self.assertGreater(p.expected_roas, 1.0)

    def test_mean_and_stddev(self):
        p = simulate_launch(_healthy(), seed=42)
        self.assertGreater(p.profit_stddev, 0)

    def test_as_dict_round_trip(self):
        p = simulate_launch(_healthy(), seed=42)
        d = p.as_dict()
        self.assertIn("profit_p50", d)
        self.assertIn("verdict", d)
        self.assertIn("candidate", d)


class TestKnobs(unittest.TestCase):
    def test_higher_break_even_floor_demotes_go(self):
        # Verdict_go at default 0.6 floor
        p_default = simulate_launch(_healthy(), seed=42)
        # With 0.99 floor even profitable candidate → caution
        p_strict = simulate_launch(
            _healthy(), seed=42, break_even_floor=0.99,
        )
        self.assertEqual(p_default.verdict, "go")
        self.assertIn(
            p_strict.verdict, ("caution", "stand_down"),
        )

    def test_profit_floor_can_demote(self):
        # Require very high median profit
        p = simulate_launch(
            _healthy(), seed=42,
            profit_floor_usd=10_000.0,
        )
        self.assertEqual(p.verdict, "caution")

    def test_n_trials_honored(self):
        p = simulate_launch(
            _healthy(), seed=42, n_trials=250,
        )
        self.assertEqual(p.n_trials, 250)

    def test_zero_trials_raises(self):
        with self.assertRaises(ValueError):
            simulate_launch(_healthy(), n_trials=0)


class TestEdgeCases(unittest.TestCase):
    def test_zero_cpc_stddev_deterministic_cpc(self):
        c = LaunchCandidate(
            cost=5, price=30,
            daily_budget_usd=20, days=3,
            est_cvr_mean=0.05, est_cvr_stddev=0.0,
            est_cpc_mean=1.0, est_cpc_stddev=0.0,
        )
        p = simulate_launch(c, seed=42)
        # With zero variance, all trials match analytically
        # impressions = 20/1 * 3 = 60, orders = 60*0.05 = 3
        # gross = 25 * 3 * 0.95 = 71.25, spend=60 → profit=11.25
        self.assertAlmostEqual(p.profit_mean, 11.25, places=1)

    def test_refund_rate_reduces_profit(self):
        base = simulate_launch(
            _healthy(refund_rate=0.0), seed=42,
        )
        refund = simulate_launch(
            _healthy(refund_rate=0.5), seed=42,
        )
        self.assertLess(
            refund.profit_p50, base.profit_p50,
        )


class TestLandedCostFactory(unittest.TestCase):
    """Wave A-2 wiring: LaunchCandidate.from_landed_cost."""

    def test_cn_us_under_deminimis_small_cost(self):
        c = LaunchCandidate.from_landed_cost(
            fob_usd=10.0,
            destination="US",
            origin="CN",
            shipping_usd=3.0,
            price=30.0,
            daily_budget_usd=20.0,
            days=3,
            de_minimis_override="active",
        )
        # Under $800 threshold → no duty, no US VAT
        # cost ≈ 10 + 3 + 0 + 0 + 10*0.029 = 13.29
        self.assertAlmostEqual(c.cost, 13.29, places=2)
        self.assertEqual(c.price, 30.0)

    def test_cn_eu_applies_vat(self):
        c = LaunchCandidate.from_landed_cost(
            fob_usd=50.0,
            destination="EU",
            origin="CN",
            price=150.0,
            daily_budget_usd=20.0,
        )
        # 20% VAT on (fob+shipping+duty) inflates cost above
        # bare FOB path
        self.assertGreater(c.cost, 50.0)

    def test_suspended_cn_increases_cost(self):
        active = LaunchCandidate.from_landed_cost(
            fob_usd=10.0,
            destination="US",
            origin="CN",
            price=30.0,
            daily_budget_usd=20.0,
            de_minimis_override="active",
        )
        suspended = LaunchCandidate.from_landed_cost(
            fob_usd=10.0,
            destination="US",
            origin="CN",
            price=30.0,
            daily_budget_usd=20.0,
            de_minimis_override="suspended_cn",
        )
        self.assertGreater(
            suspended.cost, active.cost,
        )

    def test_simulator_runs_on_landed_candidate(self):
        c = LaunchCandidate.from_landed_cost(
            fob_usd=5.0,
            destination="US",
            origin="CN",
            price=30.0,
            daily_budget_usd=20.0,
            days=3,
            est_cvr_mean=0.05,
            est_cvr_stddev=0.005,
            est_cpc_mean=1.0,
            est_cpc_stddev=0.1,
            de_minimis_override="active",
        )
        p = simulate_launch(c, seed=42)
        self.assertEqual(p.verdict, "go")


if __name__ == "__main__":
    unittest.main()
