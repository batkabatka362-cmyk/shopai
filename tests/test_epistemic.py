"""Epistemic coverage tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import epistemic as ep


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = ep.EpistemicCoverage(Path(self._tmp.name) / "e.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_observe_counts_per_dim(self) -> None:
        self.c.observe({"niche": "audio", "copy_tone": "friendly"})
        self.assertEqual(self.c.coverage("niche", "audio").n, 1)
        self.assertEqual(self.c.coverage("copy_tone", "friendly").n, 1)

    def test_case_insensitive(self) -> None:
        self.c.observe({"niche": "Audio"})
        self.c.observe({"niche": "audio"})
        self.assertEqual(self.c.coverage("niche", "AUDIO").n, 2)

    def test_unknown_dimension_skipped(self) -> None:
        n = self.c.observe({"bogus_dim": "x", "niche": "y"})
        self.assertEqual(n, 1)  # only niche counts


class TestTiers(unittest.TestCase):
    def test_cold_under_3(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = ep.EpistemicCoverage(Path(tmp.name) / "e.db")
        c.observe({"niche": "x"})
        c.observe({"niche": "x"})
        self.assertEqual(c.coverage("niche", "x").tier, "cold")
        tmp.cleanup()

    def test_warm_between_3_and_10(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = ep.EpistemicCoverage(Path(tmp.name) / "e.db")
        for _ in range(5):
            c.observe({"niche": "x"})
        self.assertEqual(c.coverage("niche", "x").tier, "warm")
        tmp.cleanup()

    def test_hot_10_or_more(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = ep.EpistemicCoverage(Path(tmp.name) / "e.db")
        for _ in range(15):
            c.observe({"niche": "x"})
        self.assertEqual(c.coverage("niche", "x").tier, "hot")
        tmp.cleanup()


class TestGaps(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = ep.EpistemicCoverage(Path(self._tmp.name) / "e.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_gaps_returns_lowest_n_first(self) -> None:
        for _ in range(20):
            self.c.observe({"niche": "hot"})
        self.c.observe({"niche": "cold"})
        gaps = self.c.gaps(top_k=2)
        self.assertEqual(gaps[0].value, "cold")
        self.assertEqual(gaps[0].tier, "cold")


class TestConfidence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = ep.EpistemicCoverage(Path(self._tmp.name) / "e.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_hot_confidence_high(self) -> None:
        for _ in range(12):
            self.c.observe({"niche": "audio", "price_band": "mid"})
        conf = self.c.confidence({"niche": "audio",
                                    "price_band": "mid"})
        self.assertAlmostEqual(conf, 1.0)

    def test_one_cold_drags_down(self) -> None:
        for _ in range(12):
            self.c.observe({"niche": "audio"})
        # price_band never observed → cold
        conf = self.c.confidence({"niche": "audio",
                                    "price_band": "premium"})
        self.assertLess(conf, 0.8)

    def test_empty_context_zero(self) -> None:
        self.assertEqual(self.c.confidence({}), 0.0)


class TestExplorationTarget(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.c = ep.EpistemicCoverage(Path(self._tmp.name) / "e.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_suggests_rarest_observed(self) -> None:
        for _ in range(5):
            self.c.observe({"niche": "common"})
        self.c.observe({"niche": "rare"})
        sug = self.c.suggest_exploration_target()
        self.assertEqual(sug.value, "rare")

    def test_returns_none_for_empty(self) -> None:
        self.assertIsNone(self.c.suggest_exploration_target())

    def test_candidate_filter_picks_unseen(self) -> None:
        for _ in range(5):
            self.c.observe({"niche": "audio"})
        sug = self.c.suggest_exploration_target(
            candidate_values={"niche": ["audio", "gardening"]},
        )
        self.assertEqual(sug.value, "gardening")


class TestSummary(unittest.TestCase):
    def test_summary_counts_by_tier(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        c = ep.EpistemicCoverage(Path(tmp.name) / "e.db")
        for _ in range(12):
            c.observe({"niche": "hot"})
        for _ in range(5):
            c.observe({"niche": "warm"})
        c.observe({"niche": "cold"})
        s = c.summary()
        self.assertEqual(s["by_tier"]["hot"], 1)
        self.assertEqual(s["by_tier"]["warm"], 1)
        self.assertEqual(s["by_tier"]["cold"], 1)
        self.assertEqual(s["total_observations"], 12 + 5 + 1)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
