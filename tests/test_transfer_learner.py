"""Transfer learner — feature extraction + grouping tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import transfer_learner as tl


class TestBanding(unittest.TestCase):
    def test_margin_bands(self) -> None:
        self.assertEqual(tl._margin_band(0.8), "high")
        self.assertEqual(tl._margin_band(0.5), "mid")
        self.assertEqual(tl._margin_band(0.2), "thin")
        self.assertEqual(tl._margin_band(0.05), "below_floor")

    def test_price_bands(self) -> None:
        self.assertEqual(tl._price_band(100), "premium")
        self.assertEqual(tl._price_band(30), "mid")
        self.assertEqual(tl._price_band(10), "impulse")
        self.assertEqual(tl._price_band(2), "giveaway")

    def test_quality_bands(self) -> None:
        self.assertEqual(tl._quality_band(90), "excellent")
        self.assertEqual(tl._quality_band(65), "ok")
        self.assertEqual(tl._quality_band(45), "weak")
        self.assertEqual(tl._quality_band(10), "unknown")


class TestFeatureFor(unittest.TestCase):
    def test_same_inputs_same_feature(self) -> None:
        row = {
            "copy_tone": "urgent", "margin_pct": 0.6,
            "target_price": 29, "gallery_size": 5,
            "has_video": True, "primary_quality": 82,
        }
        f1 = tl._feature_for(row)
        f2 = tl._feature_for(dict(row))
        self.assertEqual(f1, f2)

    def test_niche_excluded_from_feature(self) -> None:
        a = tl._feature_for({"copy_tone": "x", "target_price": 10, "niche": "audio"})
        b = tl._feature_for({"copy_tone": "x", "target_price": 10, "niche": "beauty"})
        self.assertEqual(a, b)


class TestExtractFlow(unittest.TestCase):
    def test_cross_niche_winner_promoted(self) -> None:
        launches = [
            # Audio niche with urgent tone, mid price, gallery rich — wins
            {"launch_id": "a1", "niche": "audio", "copy_tone": "urgent",
             "target_price": 30, "gallery_size": 5, "has_video": True,
             "primary_quality": 75, "verdict": "scale", "margin_pct": 0.6},
            # Beauty with same feature — also wins
            {"launch_id": "b1", "niche": "beauty", "copy_tone": "urgent",
             "target_price": 35, "gallery_size": 5, "has_video": True,
             "primary_quality": 70, "verdict": "scale", "margin_pct": 0.6},
            # Home with same feature — didn't win yet
            {"launch_id": "h1", "niche": "home", "copy_tone": "urgent",
             "target_price": 30, "gallery_size": 5, "has_video": True,
             "primary_quality": 70, "verdict": "monitor", "margin_pct": 0.6},
            # Unique feature — only one niche → filtered out
            {"launch_id": "x1", "niche": "pets", "copy_tone": "luxury",
             "target_price": 300, "gallery_size": 2, "has_video": False,
             "primary_quality": 50, "verdict": "scale", "margin_pct": 0.9},
        ]
        with patch.object(tl, "_load_launch_content", return_value=launches), \
             patch.object(tl, "_persist", return_value=True):
            report = tl.extract()

        self.assertGreaterEqual(len(report.patterns), 1)
        first = report.patterns[0]
        self.assertIn("audio", first.niches)
        self.assertIn("beauty", first.niches)
        self.assertEqual(first.wins, 2)
        self.assertGreater(first.universality, 0.5)

    def test_no_patterns_when_all_unique(self) -> None:
        launches = [
            {"launch_id": f"l{i}", "niche": f"niche{i}",
             "copy_tone": f"tone{i}", "target_price": 10 * i,
             "verdict": "scale", "margin_pct": 0.5,
             "gallery_size": i, "primary_quality": 50}
            for i in range(1, 4)
        ]
        with patch.object(tl, "_load_launch_content", return_value=launches), \
             patch.object(tl, "_persist", return_value=True):
            report = tl.extract()
        self.assertEqual(report.patterns, [])


if __name__ == "__main__":
    unittest.main()
