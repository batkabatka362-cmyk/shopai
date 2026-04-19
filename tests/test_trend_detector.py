"""Trend detector — math tests (no DB, no memory)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.autonomous import trend_detector as td


class TestComputeBasics(unittest.TestCase):
    def test_flat_series(self) -> None:
        samples = [(i, 10.0) for i in range(6)]
        t = td._compute("x", samples)
        self.assertEqual(t.trend, "flat")
        self.assertFalse(t.inflection)
        self.assertAlmostEqual(t.stddev, 0.0)

    def test_clear_upward_trend(self) -> None:
        samples = [(i, float(i) * 2 + 1) for i in range(6)]
        t = td._compute("x", samples)
        self.assertEqual(t.trend, "up")
        self.assertGreater(t.slope, 0.15)

    def test_downward_trend(self) -> None:
        # Sharper decline so normalised slope crosses the 0.15 threshold
        samples = [(i, float(100 - 15 * i)) for i in range(6)]
        t = td._compute("x", samples)
        self.assertEqual(t.trend, "down")
        self.assertLess(t.slope, -0.15)

    def test_inflection_on_sign_flip(self) -> None:
        # Rising then falling
        samples = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 2), (5, 0)]
        t = td._compute("x", samples)
        self.assertTrue(t.inflection)

    def test_inflection_on_high_zscore(self) -> None:
        # 9 points around 10, then a huge outlier
        samples = [(i, 10.0) for i in range(9)]
        samples.append((9, 30.0))
        t = td._compute("x", samples)
        self.assertTrue(t.inflection)


class TestSignFlip(unittest.TestCase):
    def test_flip_detected(self) -> None:
        window = [(0, 1), (1, 2), (2, 3), (3, 2), (4, 1), (5, 0)]
        self.assertTrue(td._sign_flip(window))

    def test_no_flip_steady_up(self) -> None:
        window = [(i, float(i)) for i in range(6)]
        self.assertFalse(td._sign_flip(window))

    def test_too_short_returns_false(self) -> None:
        self.assertFalse(td._sign_flip([(0, 1), (1, 2)]))


class TestDetectFlow(unittest.TestCase):
    def test_empty_series_returns_empty_report(self) -> None:
        with patch.object(td, "_collect_series", return_value={}):
            report = td.detect()
        self.assertEqual(report.series, [])
        self.assertEqual(report.inflections, [])
        self.assertEqual(report.recorded, 0)

    def test_insufficient_samples_skipped(self) -> None:
        # Only 2 samples in a series — below MIN_SAMPLES (3)
        with patch.object(td, "_collect_series",
                          return_value={"x/roas": [(0, 1), (1, 2)]}), \
             patch.object(td, "_persist", return_value=True):
            report = td.detect()
        self.assertEqual(report.series, [])

    def test_inflections_persisted(self) -> None:
        series = {"x/roas": [(i, 10.0) for i in range(9)] + [(9, 30.0)]}
        with patch.object(td, "_collect_series", return_value=series), \
             patch.object(td, "_persist", return_value=True) as persist:
            report = td.detect()
        self.assertEqual(report.inflection_count_or(), 1)
        persist.assert_called_once()


# Hacky accessor so the last test reads nicer
def _inflection_count(self: td.TrendReport) -> int:
    return len(self.inflections)
td.TrendReport.inflection_count_or = _inflection_count


if __name__ == "__main__":
    unittest.main()
