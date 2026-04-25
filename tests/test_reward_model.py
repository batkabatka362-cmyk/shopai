"""Reward model tests — record / score / top-preferences."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import reward_model as rm


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = rm.RewardModel(Path(self._tmp.name) / "r.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_positive_vote_raises_llr_for_that_niche(self) -> None:
        for _ in range(5):
            self.m.record({"niche": "audio", "copy_tone": "friendly"},
                          sign=+1)
        self.m.record({"niche": "fashion", "copy_tone": "friendly"},
                      sign=-1)
        est = self.m.score({"niche": "audio", "copy_tone": "friendly"})
        # audio should contribute positively
        audio_contrib = [c for c in est.contributions if c.value == "audio"]
        self.assertTrue(audio_contrib)
        self.assertGreater(audio_contrib[0].llr, 0)

    def test_zero_sign_is_noop(self) -> None:
        self.m.record({"niche": "x"}, sign=0)
        self.assertEqual(self.m.size()["total_feedback_events"], 0)

    def test_empty_features_noop(self) -> None:
        self.m.record({}, sign=+1)
        self.assertEqual(self.m.size()["total_feedback_events"], 0)


class TestScore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = rm.RewardModel(Path(self._tmp.name) / "r.db",
                                 kpi_weight=0.5)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_kpi_only_when_preference_cold(self) -> None:
        est = self.m.score({"niche": "new"}, kpi_hint=2.0)
        self.assertEqual(est.preference_term, 0.0)
        self.assertAlmostEqual(est.kpi_term, 1.0, places=2)
        self.assertAlmostEqual(est.total, 1.0, places=2)

    def test_preference_plus_kpi_composed(self) -> None:
        for _ in range(3):
            self.m.record({"niche": "audio"}, sign=+1)
        est = self.m.score({"niche": "audio"}, kpi_hint=2.0)
        self.assertGreater(est.preference_term, 0)
        self.assertGreater(est.total, est.kpi_term)

    def test_explainability_string_includes_top_features(self) -> None:
        for _ in range(4):
            self.m.record({"niche": "audio"}, sign=+1)
        est = self.m.score({"niche": "audio"}, kpi_hint=1.0)
        self.assertIn("niche=audio", est.explainability)

    def test_negative_preference_lowers_score(self) -> None:
        for _ in range(5):
            self.m.record({"copy_tone": "clickbait"}, sign=-1)
        # Counter-balance so global_counts has some positives.
        self.m.record({"copy_tone": "friendly"}, sign=+1)
        est = self.m.score({"copy_tone": "clickbait"})
        self.assertLess(est.preference_term, 0)


class TestTopPreferences(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = rm.RewardModel(Path(self._tmp.name) / "r.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_top_niche_sorted_by_abs_llr(self) -> None:
        for _ in range(10):
            self.m.record({"niche": "audio"}, sign=+1)
        for _ in range(8):
            self.m.record({"niche": "fashion"}, sign=-1)
        for _ in range(2):
            self.m.record({"niche": "audio"}, sign=-1)
        top = self.m.top_preferences("niche", k=5)
        self.assertGreater(len(top), 0)
        # First entry should be the strongest signal (audio or fashion).
        self.assertIn(top[0]["value"], {"audio", "fashion"})


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db = Path(tmp.name) / "r.db"
        m1 = rm.RewardModel(db)
        m1.record({"niche": "audio"}, sign=+1)
        m2 = rm.RewardModel(db)
        size = m2.size()
        self.assertGreater(size["total_feedback_events"], 0)
        tmp.cleanup()


class TestFractionalSign(unittest.TestCase):
    def test_half_vote_fractional_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = rm.RewardModel(Path(tmp.name) / "r.db")
        m.record({"niche": "x"}, sign=+0.5)
        # Fractional increments are treated as weighted; size should
        # register non-zero.
        self.assertGreater(m.size()["total_feedback_events"], 0)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
