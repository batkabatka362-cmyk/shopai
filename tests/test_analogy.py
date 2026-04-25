"""Analogical reasoning — distance + ranking tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import analogy as an


class TestFeatureExtraction(unittest.TestCase):
    def test_feature_extracted_from_full_row(self) -> None:
        row = {"copy_tone": "Urgent", "margin_pct": 0.5,
               "target_price": 30, "gallery_size": 5,
               "has_video": True, "primary_quality": 82,
               "niche": "Audio"}
        f = an._launch_to_feature(row)
        self.assertEqual(f["copy_tone"], "urgent")
        self.assertEqual(f["margin_band"], "mid")
        self.assertEqual(f["price_band"], "mid")
        self.assertTrue(f["gallery_rich"])
        self.assertTrue(f["has_video"])
        self.assertEqual(f["primary_quality_band"], "excellent")
        self.assertEqual(f["niche"], "audio")

    def test_returns_none_when_all_empty(self) -> None:
        self.assertIsNone(an._launch_to_feature({}))
        self.assertIsNone(an._launch_to_feature({"gallery_size": 0}))


class TestDistance(unittest.TestCase):
    def test_identical_zero_distance(self) -> None:
        f = {"copy_tone": "urgent", "margin_band": "mid",
             "price_band": "mid", "gallery_rich": True,
             "has_video": True, "primary_quality_band": "excellent",
             "niche": "audio"}
        d, shared, diff = an._weighted_hamming(f, f)
        self.assertEqual(d, 0.0)
        self.assertEqual(set(shared), set(an._WEIGHTS))
        self.assertEqual(diff, [])

    def test_tone_mismatch_adds_weight(self) -> None:
        a = {"copy_tone": "urgent", "margin_band": "mid",
             "price_band": "mid", "gallery_rich": True,
             "has_video": True, "primary_quality_band": "excellent",
             "niche": "audio"}
        b = dict(a, copy_tone="luxury")
        d, _, diff = an._weighted_hamming(a, b)
        self.assertAlmostEqual(d, an._WEIGHTS["copy_tone"])
        self.assertEqual(diff, ["copy_tone"])

    def test_none_counts_as_partial(self) -> None:
        a = {"copy_tone": "urgent", "margin_band": None,
             "price_band": "mid", "gallery_rich": True,
             "has_video": True, "primary_quality_band": "ok",
             "niche": "audio"}
        b = dict(a, margin_band="mid")
        d, _, _ = an._weighted_hamming(a, b)
        # a has None → 0.5 × weight (half-match)
        self.assertAlmostEqual(d, an._WEIGHTS["margin_band"] * 0.5)


class TestAnalogiesFlow(unittest.TestCase):
    def test_ranks_by_distance(self) -> None:
        fake_launches = [
            {"id": 1, "launch_id": "close",
             "copy_tone": "urgent", "margin_pct": 0.5,
             "target_price": 30, "gallery_size": 5, "has_video": True,
             "primary_quality": 82, "niche": "audio"},
            {"id": 2, "launch_id": "far",
             "copy_tone": "luxury", "margin_pct": 0.2,
             "target_price": 200, "gallery_size": 1, "has_video": False,
             "primary_quality": 30, "niche": "pets"},
        ]
        target = {"copy_tone": "urgent", "margin_pct": 0.5,
                  "target_price": 30, "gallery_size": 5, "has_video": True,
                  "primary_quality": 82, "niche": "audio"}
        with patch.object(an, "_load_past_launches", return_value=fake_launches), \
             patch.object(an, "_verdict_map",
                          return_value={"close": "scale", "far": "kill"}):
            out = an.analogies(target, k=2)
        self.assertEqual(out[0].launch_id, "close")
        self.assertEqual(out[0].distance, 0.0)
        self.assertLess(out[0].distance, out[1].distance)
        self.assertTrue(out[0].transferable)

    def test_returns_empty_when_target_has_no_features(self) -> None:
        self.assertEqual(an.analogies({}), [])

    def test_adaptation_hint_includes_outcome_word(self) -> None:
        diffs = ["copy_tone", "price_band"]
        self.assertIn("SCALE", an._adaptation_hint("scale", diffs))
        self.assertIn("KILLED", an._adaptation_hint("kill", diffs))
        self.assertIn("holding", an._adaptation_hint("hold", []))
        self.assertIn("unknown", an._adaptation_hint("", []))


class TestAnalogiseLaunch(unittest.TestCase):
    def test_excludes_self(self) -> None:
        fake = [
            {"id": 1, "launch_id": "target",
             "copy_tone": "urgent", "target_price": 30, "niche": "a"},
            {"id": 2, "launch_id": "other",
             "copy_tone": "urgent", "target_price": 30, "niche": "a"},
        ]
        with patch.object(an, "_load_past_launches", return_value=fake), \
             patch.object(an, "_verdict_map",
                          return_value={"target": "hold", "other": "scale"}):
            out = an.analogise_launch("target", k=1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].launch_id, "other")


if __name__ == "__main__":
    unittest.main()
