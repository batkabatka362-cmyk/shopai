"""Pricing elasticity tests."""
from __future__ import annotations

import math
import random
import unittest

from core.brain import pricing_elasticity as pe


class TestFit(unittest.TestCase):
    def test_empty_invalid(self) -> None:
        f = pe.fit([])
        self.assertFalse(f.valid)

    def test_too_few_points_invalid(self) -> None:
        f = pe.fit([
            pe.PriceObservation(price=10, units_sold=5),
            pe.PriceObservation(price=15, units_sold=3),
        ])
        self.assertFalse(f.valid)

    def test_single_price_invalid(self) -> None:
        f = pe.fit([
            pe.PriceObservation(price=20, units_sold=10),
            pe.PriceObservation(price=20, units_sold=12),
            pe.PriceObservation(price=20, units_sold=11),
        ])
        self.assertFalse(f.valid)

    def test_perfect_log_log_fit(self) -> None:
        # units = 100 / price  → ln(units) = ln(100) - 1 · ln(price)
        obs = [
            pe.PriceObservation(price=p, units_sold=100 / p)
            for p in (5, 10, 20, 40, 80)
        ]
        f = pe.fit(obs, bootstrap_samples=0)
        self.assertTrue(f.valid)
        self.assertAlmostEqual(f.beta, -1.0, places=3)
        self.assertGreater(f.r_squared, 0.99)

    def test_bootstrap_ci_returned(self) -> None:
        # Slight noise → nonzero CI width
        rng = random.Random(42)
        obs = []
        for p in (5, 10, 20, 40, 80, 100):
            noisy_units = (100 / p) * (1 + rng.uniform(-0.1, 0.1))
            obs.append(pe.PriceObservation(
                price=p, units_sold=noisy_units,
            ))
        f = pe.fit(obs, bootstrap_samples=50, rng=rng)
        self.assertIsNotNone(f.ci_low)
        self.assertIsNotNone(f.ci_high)
        self.assertLessEqual(f.ci_low, f.ci_high)

    def test_dict_observations_accepted(self) -> None:
        obs = [
            {"price": 5, "units_sold": 20},
            {"price": 10, "units_sold": 10},
            {"price": 20, "units_sold": 5},
        ]
        f = pe.fit(obs, bootstrap_samples=0)
        self.assertTrue(f.valid)

    def test_zero_units_dropped(self) -> None:
        obs = [
            pe.PriceObservation(price=5, units_sold=20),
            pe.PriceObservation(price=10, units_sold=0),
            pe.PriceObservation(price=20, units_sold=5),
        ]
        f = pe.fit(obs, bootstrap_samples=0)
        # Zero-units row dropped; only 2 left → invalid
        self.assertFalse(f.valid)


class TestPredict(unittest.TestCase):
    def test_predict_matches_fit(self) -> None:
        obs = [
            pe.PriceObservation(price=p, units_sold=100 / p)
            for p in (5, 10, 20, 40, 80)
        ]
        f = pe.fit(obs, bootstrap_samples=0)
        self.assertAlmostEqual(
            pe.predict_units(f, 16), 100 / 16, delta=0.5,
        )

    def test_invalid_fit_returns_zero(self) -> None:
        f = pe.ElasticityFit(valid=False)
        self.assertEqual(pe.predict_units(f, 10), 0.0)

    def test_negative_price_returns_zero(self) -> None:
        obs = [
            pe.PriceObservation(price=p, units_sold=100 / p)
            for p in (5, 10, 20, 40, 80)
        ]
        f = pe.fit(obs, bootstrap_samples=0)
        self.assertEqual(pe.predict_units(f, -5), 0.0)


class TestRevenueAndOptimal(unittest.TestCase):
    def setUp(self) -> None:
        obs = [
            pe.PriceObservation(price=p, units_sold=100 / (p ** 1.5))
            for p in (5, 10, 20, 40, 80)
        ]
        self.f = pe.fit(obs, bootstrap_samples=0)

    def test_revenue_at_price(self) -> None:
        rev = pe.revenue_at(self.f, 20)
        self.assertGreater(rev, 0)

    def test_optimal_price_analytic_when_elastic(self) -> None:
        # β ≈ -1.5, cost=5 → p* = -1.5*5 / (1-1.5) = 15
        self.assertTrue(self.f.is_elastic)
        star = pe.optimal_price(self.f, unit_cost=5.0)
        self.assertAlmostEqual(star, 15.0, delta=1.0)

    def test_optimal_inelastic_grid_fallback(self) -> None:
        # Flat demand: β near 0 → inelastic, grid search used
        obs = [
            pe.PriceObservation(price=p, units_sold=10)
            for p in (5, 10, 20, 40)
        ]
        f = pe.fit(obs, bootstrap_samples=0)
        star = pe.optimal_price(f, unit_cost=5.0, max_price=100)
        self.assertGreater(star, 5.0)

    def test_optimal_invalid_returns_cost(self) -> None:
        f = pe.ElasticityFit(valid=False)
        self.assertAlmostEqual(
            pe.optimal_price(f, unit_cost=12.0), 12.0,
        )


class TestObservation(unittest.TestCase):
    def test_daily_units_divides(self) -> None:
        o = pe.PriceObservation(price=10, units_sold=20, period_days=4)
        self.assertEqual(o.daily_units, 5.0)

    def test_zero_period_noop(self) -> None:
        o = pe.PriceObservation(price=10, units_sold=20, period_days=0)
        self.assertEqual(o.daily_units, 20.0)


if __name__ == "__main__":
    unittest.main()
