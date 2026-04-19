"""Anomaly detector — z-score gating tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.autonomous import anomaly_detector as ad


class TestBaselineComputation(unittest.TestCase):
    def test_baseline_needs_min_samples(self) -> None:
        launches = [
            {"launch_id": f"l{i}", "niche": "audio",
             "estimated_roas": 1.0 + i * 0.1, "aov": 20, "order_count": 2}
            for i in range(4)  # below MIN_SAMPLES_PER_NICHE
        ]
        out = ad._compute_baselines(launches)
        self.assertEqual(out, {})

    def test_baseline_computes_when_enough(self) -> None:
        launches = [
            {"launch_id": f"l{i}", "niche": "audio",
             "estimated_roas": 2.0, "aov": 25, "order_count": 3}
            for i in range(6)
        ]
        out = ad._compute_baselines(launches)
        self.assertIn("audio", out)
        self.assertAlmostEqual(out["audio"]["estimated_roas"]["mean"], 2.0)
        self.assertAlmostEqual(out["audio"]["estimated_roas"]["stddev"], 0.0)


class TestScanFlow(unittest.TestCase):
    def setUp(self) -> None:
        # Build a niche with 5 "normal" launches and 1 outlier
        self.launches = [
            {"launch_id": f"n{i}", "niche": "audio",
             "estimated_roas": 2.0, "aov": 20.0, "order_count": 3.0,
             "verdict": "hold"}
            for i in range(5)
        ] + [
            {"launch_id": "outlier", "niche": "audio",
             "estimated_roas": 0.4, "aov": 20.0, "order_count": 3.0,
             "verdict": "kill"},
        ]

    def test_detects_low_roas_outlier(self) -> None:
        # Force stddev>0 by tweaking one normal sample
        mutated = [dict(l) for l in self.launches]
        mutated[0]["estimated_roas"] = 2.2
        mutated[1]["estimated_roas"] = 1.8
        with patch.object(ad, "_load_launches", return_value=mutated), \
             patch.object(ad, "_persist", return_value=True):
            report = ad.scan()
        # The outlier should show up; direction=below
        found = [a for a in report.anomalies if a.launch_id == "outlier"]
        self.assertTrue(found, "expected 'outlier' to trip the z-score gate")
        self.assertEqual(found[0].direction, "below")
        self.assertEqual(found[0].metric, "estimated_roas")
        self.assertLess(found[0].z_score, -2.0)

    def test_no_anomalies_when_all_at_mean(self) -> None:
        flat = [
            dict(l, estimated_roas=2.0)
            for l in self.launches[:5]  # drop the outlier
        ]
        with patch.object(ad, "_load_launches", return_value=flat), \
             patch.object(ad, "_persist", return_value=True):
            report = ad.scan()
        # Stddev is 0 so every metric is skipped — no anomalies
        self.assertEqual(report.anomalies, [])

    def test_empty_launches_returns_empty(self) -> None:
        with patch.object(ad, "_load_launches", return_value=[]):
            report = ad.scan()
        self.assertEqual(report.anomalies, [])
        self.assertEqual(report.checked, 0)


if __name__ == "__main__":
    unittest.main()
