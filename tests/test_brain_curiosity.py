"""ε-greedy launch-space exploration tests (core.brain.curiosity).

Distinct from the legacy core.cognitive.curiosity module — this
tests the new launch feature-space explorer introduced in v4-D6.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import curiosity as cur


class TestFeatureCell(unittest.TestCase):
    def test_novelty_decreases_with_samples(self) -> None:
        a = cur.FeatureCell(tone="x", price_band="y", quality_band="z",
                            samples=0)
        b = cur.FeatureCell(tone="x", price_band="y", quality_band="z",
                            samples=100)
        self.assertGreater(a.novelty, b.novelty)


class TestBuildSpace(unittest.TestCase):
    def test_space_is_cartesian_product(self) -> None:
        space = cur._build_space()
        self.assertEqual(
            len(space),
            len(cur._TONES) * len(cur._PRICE_BANDS) * len(cur._QUALITY_BANDS),
        )


class TestBands(unittest.TestCase):
    def test_price_bands(self) -> None:
        self.assertEqual(cur._price_band(100), "premium")
        self.assertEqual(cur._price_band(30), "mid")
        self.assertEqual(cur._price_band(5), "impulse")

    def test_quality_bands(self) -> None:
        self.assertEqual(cur._quality_band(90), "excellent")
        self.assertEqual(cur._quality_band(65), "ok")
        self.assertEqual(cur._quality_band(45), "weak")


class TestSuggest(unittest.TestCase):
    def test_exploit_when_epsilon_zero(self) -> None:
        with patch.object(cur, "_populate_samples"), \
             patch.object(cur, "_persist"):
            hint = cur.suggest(epsilon=0.0, seed=1)
        self.assertEqual(hint.mode, "exploit")

    def test_explore_when_epsilon_one(self) -> None:
        with patch.object(cur, "_populate_samples"), \
             patch.object(cur, "_persist"):
            hint = cur.suggest(epsilon=1.0, seed=1)
        self.assertEqual(hint.mode, "explore")

    def test_explore_picks_least_explored(self) -> None:
        def seed_samples(cells):
            cells[0].samples = 10
        with patch.object(cur, "_populate_samples", side_effect=seed_samples), \
             patch.object(cur, "_persist"):
            hint = cur.suggest(epsilon=1.0, seed=1)
        self.assertEqual(hint.cell.samples, 0)
        self.assertNotEqual(hint.cell.key, cur._build_space()[0].key)

    def test_exploit_picks_best_win_rate(self) -> None:
        def seed_samples(cells):
            cells[0].samples = 10
            cells[0].wins = 8     # 80%
            cells[1].samples = 10
            cells[1].wins = 3     # 30%
        with patch.object(cur, "_populate_samples", side_effect=seed_samples), \
             patch.object(cur, "_persist"):
            hint = cur.suggest(epsilon=0.0, seed=1)
        self.assertEqual(hint.mode, "exploit")
        self.assertEqual(hint.cell.wins, 8)


class TestStats(unittest.TestCase):
    def test_coverage_reported(self) -> None:
        def seed_samples(cells):
            cells[0].samples = 3
        with patch.object(cur, "_populate_samples", side_effect=seed_samples):
            s = cur.stats()
        self.assertEqual(s["explored_cells"], 1)
        self.assertEqual(
            s["total_cells"],
            len(cur._TONES) * len(cur._PRICE_BANDS) * len(cur._QUALITY_BANDS),
        )


if __name__ == "__main__":
    unittest.main()
