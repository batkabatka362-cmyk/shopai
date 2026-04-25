"""Price elasticity tests."""
from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from core.brain import price_elasticity as pe


class TestObserve(unittest.TestCase):
    def test_observe_blank_segment(self) -> None:
        e = pe.PriceElasticity()
        with self.assertRaises(ValueError):
            e.observe("", price=10, units=5)

    def test_observe_negative_price(self) -> None:
        e = pe.PriceElasticity()
        with self.assertRaises(ValueError):
            e.observe("s", price=-1, units=5)

    def test_min_samples_invalid(self) -> None:
        with self.assertRaises(ValueError):
            pe.PriceElasticity(min_samples=1)


class TestFit(unittest.TestCase):
    def test_fit_below_threshold_insufficient(self) -> None:
        e = pe.PriceElasticity(min_samples=5)
        e.observe("s", price=10, units=10)
        fit = e.fit("s")
        self.assertEqual(fit.status, "insufficient")

    def test_fit_recovers_known_elasticity(self) -> None:
        # Synthesise a clean curve units = 1000 × price^(-2)
        e = pe.PriceElasticity(min_samples=3)
        for p in (10.0, 20.0, 30.0, 40.0, 50.0):
            units = 1000.0 / (p ** 2)
            e.observe("s", price=p, units=units)
        fit = e.fit("s")
        self.assertEqual(fit.status, "ok")
        self.assertAlmostEqual(fit.elasticity, -2.0, places=2)
        self.assertGreater(fit.r_squared, 0.99)

    def test_zero_units_dropped(self) -> None:
        e = pe.PriceElasticity(min_samples=3)
        for p in (10.0, 20.0, 30.0):
            e.observe("s", price=p, units=0)
        fit = e.fit("s")
        # All zero-units → degenerate (no usable rows after drop)
        self.assertEqual(fit.status, "degenerate")

    def test_constant_price_degenerate(self) -> None:
        e = pe.PriceElasticity(min_samples=3)
        for _ in range(5):
            e.observe("s", price=10, units=20)
        fit = e.fit("s")
        # Zero variance in price → degenerate
        self.assertEqual(fit.status, "degenerate")


class TestPredict(unittest.TestCase):
    def setUp(self) -> None:
        self.e = pe.PriceElasticity(min_samples=3)
        for p in (10.0, 20.0, 30.0, 40.0, 50.0):
            units = 1000.0 / (p ** 2)
            self.e.observe("audio", price=p, units=units)

    def test_predict_at_known_point(self) -> None:
        pred = self.e.predict("audio", price=20.0)
        # 1000 / 20^2 = 2.5 units
        self.assertAlmostEqual(pred.units, 2.5, places=1)
        self.assertAlmostEqual(pred.revenue, 50.0, places=1)

    def test_predict_extrapolates_consistent(self) -> None:
        pred = self.e.predict("audio", price=100.0)
        # 1000 / 100^2 = 0.1
        self.assertLess(pred.units, 1.0)

    def test_predict_zero_price_none(self) -> None:
        self.assertIsNone(self.e.predict("audio", price=0.0))

    def test_predict_unknown_segment_none(self) -> None:
        self.assertIsNone(self.e.predict("nope", price=10.0))


class TestOptimalRevenuePrice(unittest.TestCase):
    def test_picks_highest_revenue(self) -> None:
        e = pe.PriceElasticity(min_samples=3)
        # Manually craft a curve where revenue peaks at $25.
        # units = 100 / (p ** 0.5)
        # revenue = p × 100 / p^0.5 = 100 × p^0.5  (monotone ↑)
        for p in (10, 20, 30, 40):
            e.observe("s", price=p, units=100 / math.sqrt(p))
        best = e.optimal_revenue_price(
            "s", candidates=[10, 20, 30, 40, 50],
        )
        self.assertEqual(best.price, 50)

    def test_no_candidates_none(self) -> None:
        e = pe.PriceElasticity(min_samples=3)
        for p in (10.0, 20.0, 30.0):
            e.observe("s", price=p, units=10 / p)
        self.assertIsNone(e.optimal_revenue_price("s", candidates=[]))

    def test_unfit_segment_none(self) -> None:
        e = pe.PriceElasticity(min_samples=10)
        e.observe("s", price=10.0, units=5.0)
        self.assertIsNone(e.optimal_revenue_price("s", candidates=[10, 20]))


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "p.db"
        first = pe.PriceElasticity(db_path=path, min_samples=3)
        for p in (10.0, 20.0, 30.0):
            first.observe("s", price=p, units=10 / p)
        first.close()
        second = pe.PriceElasticity(db_path=path, min_samples=3)
        self.assertEqual(second.stats()["samples"], 3)
        self.assertEqual(second.fit("s").status, "ok")
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        e = pe.PriceElasticity(min_samples=3)
        e.observe("a", price=10, units=5)
        e.observe("b", price=10, units=5)
        s = e.stats()
        self.assertEqual(s["segments"], 2)
        self.assertEqual(s["samples"], 2)


class TestReset(unittest.TestCase):
    def test_reset_segment(self) -> None:
        e = pe.PriceElasticity()
        e.observe("a", price=10, units=5)
        e.observe("b", price=10, units=5)
        n = e.reset("a")
        self.assertEqual(n, 1)
        self.assertEqual(e.stats()["segments"], 1)

    def test_reset_all(self) -> None:
        e = pe.PriceElasticity()
        e.observe("a", price=10, units=5)
        n = e.reset()
        self.assertEqual(n, 1)
        self.assertEqual(e.stats()["samples"], 0)


class TestDict(unittest.TestCase):
    def test_fit_serialises(self) -> None:
        e = pe.PriceElasticity(min_samples=3)
        for p in (10.0, 20.0, 30.0):
            e.observe("s", price=p, units=10 / p)
        d = e.fit("s").as_dict()
        self.assertIn("elasticity", d)
        self.assertIn("status", d)

    def test_prediction_serialises(self) -> None:
        e = pe.PriceElasticity(min_samples=3)
        for p in (10.0, 20.0, 30.0):
            e.observe("s", price=p, units=10 / p)
        d = e.predict("s", price=15.0).as_dict()
        self.assertIn("revenue", d)


if __name__ == "__main__":
    unittest.main()
