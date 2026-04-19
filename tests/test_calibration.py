"""Calibration tracker — Brier + reliability diagram tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import calibration as cal


class TestReliabilityDiagram(unittest.TestCase):
    def test_buckets_capture_predictions(self) -> None:
        # 5 predictions, split across buckets
        pairs = [(0.05, 0), (0.15, 0), (0.55, 1), (0.85, 1), (0.95, 1)]
        buckets = cal._reliability_diagram(pairs)
        # Expect 4 non-empty buckets (0-10%, 10-20%, 50-60%, 80-90%, 90-100%)
        self.assertEqual(len(buckets), 5)
        # 90-100 bucket should have predicted mean ≈ 0.95 and actual 1.0
        top = [b for b in buckets if b.lo >= 0.9][0]
        self.assertAlmostEqual(top.predicted_mean, 0.95)
        self.assertAlmostEqual(top.actual_rate, 1.0)


class TestScoreFlow(unittest.TestCase):
    def test_empty_pairs_returns_blank_report(self) -> None:
        with patch.object(cal, "_collect_pairs", return_value=[]), \
             patch.object(cal, "_persist", return_value=True):
            report = cal.score()
        self.assertEqual(report.samples, 0)
        self.assertEqual(report.brier_score, 1.0)
        self.assertEqual(report.level, "unknown")

    def test_perfect_calibration(self) -> None:
        # Predictor always says 100 % and the outcome is always 1
        pairs = [(1.0, 1.0)] * 10
        with patch.object(cal, "_collect_pairs", return_value=pairs), \
             patch.object(cal, "_persist", return_value=True):
            report = cal.score()
        self.assertAlmostEqual(report.brier_score, 0.0)
        self.assertAlmostEqual(report.bias, 0.0)
        self.assertEqual(report.level, "good")

    def test_over_confident_drift(self) -> None:
        # Predicts 90 % win but actual outcome 0 most of the time
        pairs = [(0.9, 0)] * 10 + [(0.9, 1)] * 2
        with patch.object(cal, "_collect_pairs", return_value=pairs), \
             patch.object(cal, "_persist", return_value=True):
            report = cal.score()
        # Bias = mean(0.9 - y) ≈ +0.75
        self.assertGreater(report.bias, 0.15)
        self.assertEqual(report.level, "drift")

    def test_random_predictor_is_noisy(self) -> None:
        # Predictor always says 50 %, outcomes split evenly → Brier 0.25
        pairs = [(0.5, 1)] * 10 + [(0.5, 0)] * 10
        with patch.object(cal, "_collect_pairs", return_value=pairs), \
             patch.object(cal, "_persist", return_value=True):
            report = cal.score()
        self.assertAlmostEqual(report.brier_score, 0.25)
        # bias = 0 → not drift, but brier > 0.15 → ok (not "good")
        self.assertAlmostEqual(report.bias, 0.0)
        self.assertIn(report.level, {"noisy", "ok"})


class TestLevelThresholds(unittest.TestCase):
    def test_good_level(self) -> None:
        r = cal.CalibrationReport(samples=100, brier_score=0.1, bias=0.02)
        self.assertEqual(r.level, "good")

    def test_drift_level(self) -> None:
        r = cal.CalibrationReport(samples=100, brier_score=0.15, bias=0.2)
        self.assertEqual(r.level, "drift")

    def test_noisy_level(self) -> None:
        r = cal.CalibrationReport(samples=100, brier_score=0.35, bias=0.05)
        self.assertEqual(r.level, "noisy")

    def test_unknown_when_zero_samples(self) -> None:
        r = cal.CalibrationReport(samples=0)
        self.assertEqual(r.level, "unknown")


if __name__ == "__main__":
    unittest.main()
