"""Learning curve tracker tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import learning_curve as lc


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = lc.LearningCurveTracker(Path(self._tmp.name) / "lc.db")

    def tearDown(self) -> None:
        self.t.close()
        self._tmp.cleanup()

    def test_record_and_read_back(self) -> None:
        self.t.record("brain", "acc", 0.7, cycle=1)
        self.t.record("brain", "acc", 0.75, cycle=2)
        pts = self.t.points("brain", "acc")
        self.assertEqual(len(pts), 2)
        self.assertEqual(pts[0].value, 0.7)
        self.assertEqual(pts[1].value, 0.75)

    def test_cycle_auto_increments(self) -> None:
        self.t.record("brain", "acc", 0.5)
        self.t.record("brain", "acc", 0.6)
        pts = self.t.points("brain", "acc")
        self.assertEqual(pts[0].cycle, 1)
        self.assertEqual(pts[1].cycle, 2)

    def test_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.record("", "m", 0.5)

    def test_isolated_per_metric(self) -> None:
        self.t.record("brain", "acc", 0.7, cycle=1)
        self.t.record("brain", "f1", 0.4, cycle=1)
        self.assertEqual(len(self.t.points("brain", "acc")), 1)
        self.assertEqual(len(self.t.points("brain", "f1")), 1)


class TestCurveImproving(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = lc.LearningCurveTracker(Path(self._tmp.name) / "lc.db")

    def tearDown(self) -> None:
        self.t.close()
        self._tmp.cleanup()

    def test_monotonic_increase_flagged_improving(self) -> None:
        for i in range(1, 11):
            self.t.record("brain", "acc", 0.5 + i * 0.02, cycle=i)
        c = self.t.curve("brain", "acc")
        self.assertEqual(c.trend, "improving")
        self.assertGreater(c.slope, 0)
        self.assertAlmostEqual(c.slope, 0.02, places=3)

    def test_delta_vs_start(self) -> None:
        for i in range(1, 11):
            self.t.record("brain", "acc", 0.5 + i * 0.02, cycle=i)
        c = self.t.curve("brain", "acc")
        self.assertGreater(c.delta, 0.15)


class TestCurveRegressing(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = lc.LearningCurveTracker(Path(self._tmp.name) / "lc.db")

    def tearDown(self) -> None:
        self.t.close()
        self._tmp.cleanup()

    def test_monotonic_decrease_flagged_regressing(self) -> None:
        for i in range(1, 11):
            self.t.record("brain", "acc", 0.9 - i * 0.02, cycle=i)
        c = self.t.curve("brain", "acc")
        self.assertEqual(c.trend, "regressing")
        self.assertLess(c.slope, 0)


class TestCurvePlateau(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = lc.LearningCurveTracker(Path(self._tmp.name) / "lc.db")

    def tearDown(self) -> None:
        self.t.close()
        self._tmp.cleanup()

    def test_flat_series_is_plateau(self) -> None:
        for i in range(1, 11):
            self.t.record("brain", "acc", 0.7, cycle=i)
        c = self.t.curve("brain", "acc")
        self.assertEqual(c.trend, "plateau")

    def test_insufficient_single_point(self) -> None:
        self.t.record("brain", "acc", 0.7, cycle=1)
        c = self.t.curve("brain", "acc")
        self.assertEqual(c.trend, "insufficient")
        self.assertEqual(c.n, 1)

    def test_insufficient_zero_points(self) -> None:
        c = self.t.curve("brain", "acc")
        self.assertEqual(c.trend, "insufficient")
        self.assertEqual(c.n, 0)


class TestRSquared(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = lc.LearningCurveTracker(Path(self._tmp.name) / "lc.db")

    def tearDown(self) -> None:
        self.t.close()
        self._tmp.cleanup()

    def test_perfect_line_r2_near_one(self) -> None:
        for i in range(1, 11):
            self.t.record("brain", "acc", i * 0.1, cycle=i)
        c = self.t.curve("brain", "acc")
        self.assertGreater(c.r_squared, 0.99)

    def test_noisy_series_low_r2(self) -> None:
        noise = [0.5, 0.2, 0.8, 0.1, 0.9, 0.3, 0.7, 0.4, 0.6, 0.5]
        for i, v in enumerate(noise, 1):
            self.t.record("brain", "acc", v, cycle=i)
        c = self.t.curve("brain", "acc")
        self.assertLess(c.r_squared, 0.3)


class TestWindow(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = lc.LearningCurveTracker(Path(self._tmp.name) / "lc.db")

    def tearDown(self) -> None:
        self.t.close()
        self._tmp.cleanup()

    def test_window_limits_points(self) -> None:
        for i in range(1, 21):
            self.t.record("brain", "acc", i * 0.01, cycle=i)
        c = self.t.curve("brain", "acc", window=5)
        self.assertEqual(c.n, 5)


class TestRank(unittest.TestCase):
    def test_fastest_improver_first(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        t = lc.LearningCurveTracker(Path(tmp.name) / "lc.db")
        for i in range(1, 11):
            t.record("fast", "acc", i * 0.05, cycle=i)
            t.record("slow", "acc", i * 0.01, cycle=i)
            t.record("down", "acc", 1.0 - i * 0.02, cycle=i)
        ranked = t.rank("acc")
        self.assertEqual(ranked[0].subsystem, "fast")
        self.assertEqual(ranked[-1].subsystem, "down")
        t.close()
        tmp.cleanup()


class TestForecast(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = lc.LearningCurveTracker(Path(self._tmp.name) / "lc.db")

    def tearDown(self) -> None:
        self.t.close()
        self._tmp.cleanup()

    def test_forecast_extends_trend(self) -> None:
        for i in range(1, 11):
            self.t.record("brain", "acc", i * 0.1, cycle=i)
        fcast = self.t.forecast("brain", "acc", steps=3)
        self.assertEqual(len(fcast), 3)
        # Last actual was 1.0 @ cycle 10, slope 0.1
        self.assertAlmostEqual(fcast[0], 1.1, places=2)
        self.assertAlmostEqual(fcast[2], 1.3, places=2)

    def test_insufficient_returns_flat(self) -> None:
        self.t.record("brain", "acc", 0.5, cycle=1)
        fcast = self.t.forecast("brain", "acc", steps=4)
        self.assertEqual(fcast, [0.5] * 4)


class TestClear(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.t = lc.LearningCurveTracker(Path(self._tmp.name) / "lc.db")

    def tearDown(self) -> None:
        self.t.close()
        self._tmp.cleanup()

    def test_clear_subsystem(self) -> None:
        self.t.record("a", "m", 0.5, cycle=1)
        self.t.record("b", "m", 0.5, cycle=1)
        n = self.t.clear(subsystem="a")
        self.assertEqual(n, 1)
        self.assertEqual(len(self.t.points("a", "m")), 0)
        self.assertEqual(len(self.t.points("b", "m")), 1)

    def test_clear_all(self) -> None:
        self.t.record("a", "m", 0.5, cycle=1)
        self.t.record("b", "m", 0.5, cycle=1)
        n = self.t.clear()
        self.assertEqual(n, 2)


class TestDict(unittest.TestCase):
    def test_curve_as_dict(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        t = lc.LearningCurveTracker(Path(tmp.name) / "lc.db")
        for i in range(1, 6):
            t.record("brain", "acc", i * 0.1, cycle=i)
        d = t.curve("brain", "acc").as_dict()
        self.assertIn("slope", d)
        self.assertIn("trend", d)
        self.assertIn("r_squared", d)
        t.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
