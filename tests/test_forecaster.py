"""Forecaster tests."""
from __future__ import annotations

import unittest

from core.brain import forecaster as fc


class TestConfig(unittest.TestCase):
    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            fc.Forecaster(window=2)

    def test_bad_alpha_raises(self) -> None:
        with self.assertRaises(ValueError):
            fc.Forecaster(ema_alpha=0)
        with self.assertRaises(ValueError):
            fc.Forecaster(ema_alpha=1.5)


class TestLinearFit(unittest.TestCase):
    def test_perfect_line_zero_residual(self) -> None:
        xs = [0.0, 1.0, 2.0, 3.0]
        ys = [1.0, 3.0, 5.0, 7.0]
        slope, intercept, resid = fc._linear_fit(xs, ys)
        self.assertAlmostEqual(slope, 2.0)
        self.assertAlmostEqual(intercept, 1.0)
        self.assertAlmostEqual(resid, 0.0)

    def test_flat_data_zero_slope(self) -> None:
        xs = [0.0, 1.0, 2.0]
        ys = [5.0, 5.0, 5.0]
        slope, intercept, _ = fc._linear_fit(xs, ys)
        self.assertEqual(slope, 0.0)
        self.assertEqual(intercept, 5.0)

    def test_single_point_safe(self) -> None:
        slope, intercept, resid = fc._linear_fit([0.0], [5.0])
        self.assertEqual(slope, 0.0)
        self.assertEqual(intercept, 5.0)
        self.assertEqual(resid, 0.0)


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self.f = fc.Forecaster(window=10)

    def test_blank_kpi_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.f.observe("", 1.0)

    def test_window_caps_buffer(self) -> None:
        for i in range(20):
            self.f.observe("k", float(i))
        self.assertEqual(self.f.stats()["samples"]["k"], 10)

    def test_explicit_ts_respected(self) -> None:
        self.f.observe("k", 1.0, ts=1000.0)
        self.f.observe("k", 2.0, ts=2000.0)
        self.assertEqual(self.f.stats()["samples"]["k"], 2)


class TestEmpty(unittest.TestCase):
    def test_empty_kpi_zero_projection(self) -> None:
        f = fc.Forecaster()
        p = f.forecast("never_seen")
        self.assertEqual(p.n_samples, 0)
        self.assertEqual(p.value, 0.0)
        self.assertEqual(p.method, "empty")


class TestFlatline(unittest.TestCase):
    def test_two_points_flatlines_at_ema(self) -> None:
        f = fc.Forecaster()
        f.observe("k", 5.0)
        f.observe("k", 7.0)
        p = f.forecast("k")
        self.assertEqual(p.method, "ema_flatline")
        self.assertGreaterEqual(p.value, 5.0)
        self.assertLessEqual(p.value, 7.0)


class TestForecast(unittest.TestCase):
    def test_trend_projects_forward(self) -> None:
        f = fc.Forecaster(window=20)
        for i in range(10):
            f.observe("k", float(i))
        p = f.forecast("k", horizon_steps=3)
        # Positive trend should push projection above last value
        self.assertGreater(p.value, 9.0)
        self.assertGreater(p.trend_slope, 0)

    def test_flat_series_zero_slope(self) -> None:
        f = fc.Forecaster(window=20)
        for _ in range(10):
            f.observe("k", 5.0)
        p = f.forecast("k", horizon_steps=3)
        self.assertAlmostEqual(p.trend_slope, 0.0)
        self.assertAlmostEqual(p.value, 5.0)

    def test_uncertainty_band_contains_value(self) -> None:
        f = fc.Forecaster(window=20)
        import random
        random.seed(42)
        for i in range(15):
            f.observe("k", i + random.gauss(0, 0.2))
        p = f.forecast("k")
        self.assertLessEqual(p.lower, p.value)
        self.assertLessEqual(p.value, p.upper)

    def test_horizon_must_be_positive(self) -> None:
        f = fc.Forecaster()
        f.observe("k", 1.0)
        with self.assertRaises(ValueError):
            f.forecast("k", horizon_steps=0)


class TestDeseasonalise(unittest.TestCase):
    def test_hour_buckets_subtract_mean(self) -> None:
        f = fc.Forecaster(window=200)
        # Force values at hour 12 and hour 18
        base_ts = 1_760_000_000  # deterministic epoch
        for h in (12, 18):
            # Two samples at each hour so the bucket has a mean
            for v in (10.0, 12.0):
                f.observe(
                    "k", v,
                    ts=base_ts + (h * 3600),
                )
        deseas = f.deseasonalise("k", bucket_key="hour")
        self.assertEqual(len(deseas), 4)
        # Each value minus the bucket mean should centre near 0
        self.assertAlmostEqual(sum(deseas) / len(deseas), 0.0)

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(fc.Forecaster().deseasonalise("k"), [])


class TestReset(unittest.TestCase):
    def test_reset_single_kpi(self) -> None:
        f = fc.Forecaster()
        for _ in range(5):
            f.observe("a", 1.0)
        for _ in range(5):
            f.observe("b", 2.0)
        self.assertEqual(f.reset("a"), 5)
        self.assertEqual(f.stats()["samples"].get("a"), None)

    def test_reset_all(self) -> None:
        f = fc.Forecaster()
        f.observe("a", 1.0)
        f.observe("b", 1.0)
        self.assertEqual(f.reset(), 2)


class TestDict(unittest.TestCase):
    def test_projection_as_dict(self) -> None:
        f = fc.Forecaster(window=10)
        for i in range(5):
            f.observe("k", float(i))
        d = f.forecast("k").as_dict()
        self.assertIn("method", d)
        self.assertIn("trend_slope", d)


if __name__ == "__main__":
    unittest.main()
