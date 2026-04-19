"""Theory of mind — v5-D4 customer + competitor belief tests.

Distinct from tests/test_theory_of_mind.py which covers the
pre-existing TheoryOfMind cognitive module. This new module lives
under core.brain.theory_of_mind and targets market agents
(customers, competitors) rather than external-agent planning.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import theory_of_mind as tom


class TestPriceBand(unittest.TestCase):
    def test_bands(self) -> None:
        self.assertEqual(tom._price_band(100), "premium")
        self.assertEqual(tom._price_band(30), "mid")
        self.assertEqual(tom._price_band(10), "impulse")
        self.assertEqual(tom._price_band(2), "giveaway")


class TestMonotonicRun(unittest.TestCase):
    def test_finds_longest_cut_run(self) -> None:
        self.assertEqual(
            tom._monotonic_run([-5, -3, -1, 2, -2, -1], negative=True), 3,
        )

    def test_no_cuts_returns_zero(self) -> None:
        self.assertEqual(
            tom._monotonic_run([1, 2, 3, 4], negative=True), 0,
        )


class TestReactivity(unittest.TestCase):
    def test_frequent_moves_high_reactivity(self) -> None:
        rows = [{"ts": i * 86400} for i in range(5)]
        self.assertAlmostEqual(tom._compute_reactivity(rows), 0.9)

    def test_rare_moves_low_reactivity(self) -> None:
        rows = [{"ts": i * 86400 * 30} for i in range(3)]
        self.assertEqual(tom._compute_reactivity(rows), 0.1)

    def test_single_sample_zero(self) -> None:
        self.assertEqual(tom._compute_reactivity([{"ts": 0}]), 0.0)


class TestCustomerBelief(unittest.TestCase):
    def test_segments_aggregated(self) -> None:
        orders = [
            {"customer_email": "a", "source_name": "web", "total_price": 20, "line_count": 1},
            {"customer_email": "a", "source_name": "web", "total_price": 30, "line_count": 2},
            {"customer_email": "b", "source_name": "meta_ads", "total_price": 50, "line_count": 1},
        ]
        with patch.object(tom, "_pull_orders", return_value=orders), \
             patch.object(tom, "_persist"):
            b = tom.customer_belief()
        self.assertEqual(b.total_orders, 3)
        self.assertEqual(b.total_customers, 2)
        self.assertAlmostEqual(b.global_repeat_rate, 0.5)
        # 3 segments because $20 = impulse, $30 = mid, $50 = mid
        self.assertEqual(len(b.segments), 3)
        keys = {s.segment_key for s in b.segments}
        self.assertIn("web_impulse", keys)
        self.assertIn("web_mid", keys)
        self.assertIn("meta_ads_mid", keys)

    def test_empty_returns_zero_belief(self) -> None:
        with patch.object(tom, "_pull_orders", return_value=[]):
            b = tom.customer_belief()
        self.assertEqual(b.total_orders, 0)
        self.assertEqual(b.segments, [])


class TestCompetitorBelief(unittest.TestCase):
    def test_builds_per_url_belief(self) -> None:
        events = [
            {"content": {"url": "https://x.com/a", "new_price": 30,
                          "delta_pct": -5, "title": "Gadget A"},
             "ts": 1_000_000},
            {"content": {"url": "https://x.com/a", "new_price": 25,
                          "delta_pct": -16, "title": "Gadget A"},
             "ts": 1_086_400},
            {"content": {"url": "https://x.com/b", "new_price": 100,
                          "delta_pct": 20, "title": "Gadget B"},
             "ts": 1_000_000},
        ]
        with patch.object(tom, "_pull_events_by_category", return_value=events), \
             patch.object(tom, "_persist"):
            beliefs = tom.competitor_belief()
        self.assertEqual(len(beliefs), 2)
        a = next(b for b in beliefs if b.url == "https://x.com/a")
        self.assertEqual(a.monotonic_cuts, 2)
        self.assertEqual(a.last_price, 25)
        self.assertEqual(a.title, "Gadget A")

    def test_empty_returns_empty_list(self) -> None:
        with patch.object(tom, "_pull_events_by_category", return_value=[]), \
             patch.object(tom, "_persist"):
            self.assertEqual(tom.competitor_belief(), [])


if __name__ == "__main__":
    unittest.main()
