"""Causal graph tests."""
from __future__ import annotations

import random
import unittest

from core.brain import causal_graph as cg


class TestPearson(unittest.TestCase):
    def test_perfect_positive(self) -> None:
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [2.0, 4.0, 6.0, 8.0]
        self.assertAlmostEqual(cg._pearson(xs, ys), 1.0)

    def test_perfect_negative(self) -> None:
        xs = [1.0, 2.0, 3.0, 4.0]
        ys = [8.0, 6.0, 4.0, 2.0]
        self.assertAlmostEqual(cg._pearson(xs, ys), -1.0)

    def test_zero_variance_safe(self) -> None:
        xs = [5.0] * 5
        ys = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertEqual(cg._pearson(xs, ys), 0.0)

    def test_length_mismatch_safe(self) -> None:
        self.assertEqual(cg._pearson([1, 2], [1, 2, 3]), 0.0)


class TestPartialCorrelation(unittest.TestCase):
    def test_partial_survives_unrelated_z(self) -> None:
        random.seed(42)
        xs = [random.gauss(0, 1) for _ in range(100)]
        ys = [x + random.gauss(0, 0.1) for x in xs]
        zs = [random.gauss(0, 1) for _ in range(100)]
        r = cg._partial_correlation(xs, ys, zs)
        # Should stay strongly positive
        self.assertGreater(r, 0.8)

    def test_partial_collapses_on_confounder(self) -> None:
        random.seed(42)
        # Z drives both X and Y → spurious correlation
        zs = [random.gauss(0, 1) for _ in range(100)]
        xs = [z + random.gauss(0, 0.1) for z in zs]
        ys = [z + random.gauss(0, 0.1) for z in zs]
        r = cg._partial_correlation(xs, ys, zs)
        # Conditioning on Z should drop correlation to near 0
        self.assertLess(abs(r), 0.4)


class TestObserve(unittest.TestCase):
    def test_observe_rejects_blank_kpi(self) -> None:
        g = cg.CausalGraph()
        with self.assertRaises(ValueError):
            g.observe({"x": 1}, kpi="", value=1.0)

    def test_numeric_coercion(self) -> None:
        g = cg.CausalGraph(min_correlation=0.0)
        for i in range(5):
            g.observe(
                {"x": "not a number", "y": float(i)},
                kpi="k", value=float(i),
            )
        # Only y survives as numeric
        report = g.report("k")
        features = [v.feature for v in report.verdicts]
        self.assertIn("y", features)
        self.assertNotIn("x", features)

    def test_max_cap_drops_oldest(self) -> None:
        g = cg.CausalGraph(max_observations=5)
        for i in range(20):
            g.observe({"x": float(i)}, kpi="k", value=float(i))
        self.assertEqual(g.stats()["n_obs"], 5)

    def test_config_raises(self) -> None:
        with self.assertRaises(ValueError):
            cg.CausalGraph(max_observations=0)
        with self.assertRaises(ValueError):
            cg.CausalGraph(min_correlation=-0.1)


class TestReport(unittest.TestCase):
    def test_true_driver_surfaces(self) -> None:
        random.seed(42)
        g = cg.CausalGraph()
        for _ in range(200):
            spend = random.uniform(0, 100)
            noise = random.uniform(0, 100)
            revenue = spend * 2 + random.gauss(0, 5)
            g.observe(
                {"ad_spend": spend, "random_noise": noise},
                kpi="revenue", value=revenue,
            )
        report = g.report("revenue")
        drivers = [v.feature for v in report.verdicts if v.status == "driver"]
        self.assertIn("ad_spend", drivers)
        self.assertNotIn("random_noise", drivers)

    def test_confounder_flagged(self) -> None:
        random.seed(42)
        g = cg.CausalGraph(shrinkage_threshold=0.4)
        for _ in range(300):
            time_of_day = random.uniform(0, 24)
            # Both ad_views and revenue driven by time_of_day
            ad_views = time_of_day * 10 + random.gauss(0, 2)
            revenue = time_of_day * 5 + random.gauss(0, 2)
            g.observe(
                {"ad_views": ad_views, "time_of_day": time_of_day},
                kpi="revenue", value=revenue,
            )
        report = g.report("revenue")
        # ad_views looks correlated but time_of_day is the real driver
        ad_views_verdict = next(
            v for v in report.verdicts if v.feature == "ad_views"
        )
        self.assertIn("time_of_day", ad_views_verdict.confounders)

    def test_low_correlation_marked_noise(self) -> None:
        random.seed(42)
        g = cg.CausalGraph(min_correlation=0.3)
        for _ in range(200):
            g.observe(
                {"noise": random.gauss(0, 1)},
                kpi="y", value=random.gauss(0, 1),
            )
        report = g.report("y")
        for v in report.verdicts:
            if v.feature == "noise":
                self.assertEqual(v.status, "noise")

    def test_too_few_obs_empty_verdicts(self) -> None:
        g = cg.CausalGraph()
        g.observe({"x": 1}, kpi="y", value=1)
        self.assertEqual(g.report("y").verdicts, [])

    def test_drivers_shortcut(self) -> None:
        random.seed(42)
        g = cg.CausalGraph()
        for _ in range(200):
            spend = random.uniform(0, 100)
            revenue = spend * 2 + random.gauss(0, 3)
            g.observe({"spend": spend}, kpi="revenue", value=revenue)
        self.assertIn("spend", g.drivers("revenue"))


class TestClear(unittest.TestCase):
    def test_clear_all(self) -> None:
        g = cg.CausalGraph()
        g.observe({"x": 1}, kpi="a", value=1)
        n = g.clear()
        self.assertEqual(n, 1)
        self.assertEqual(g.stats()["n_obs"], 0)

    def test_clear_single_kpi(self) -> None:
        g = cg.CausalGraph()
        g.observe({"x": 1}, kpi="a", value=1)
        g.observe({"x": 1}, kpi="b", value=1)
        self.assertEqual(g.clear(kpi="a"), 1)
        self.assertEqual(g.stats()["n_obs"], 1)


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        g = cg.CausalGraph()
        for _ in range(5):
            g.observe({"x": 1}, kpi="y", value=1)
        d = g.report("y").as_dict()
        self.assertIn("verdicts", d)
        self.assertIn("drivers", d)


if __name__ == "__main__":
    unittest.main()
