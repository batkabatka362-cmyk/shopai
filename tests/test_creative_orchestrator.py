"""Creative orchestrator — statistical scoring + promotion tests."""
from __future__ import annotations

import unittest

from core.brain import creative_orchestrator as co


class TestScore(unittest.TestCase):
    def test_zero_impressions_zero_everywhere(self) -> None:
        v = co._score({"variant_id": "v", "launch_id": "l"})
        self.assertEqual(v.ctr, 0)
        self.assertEqual(v.roas, 0)
        self.assertEqual(v.roas_lower_95, 0)
        self.assertEqual(v.roas_upper_95, 0)

    def test_basic_rates(self) -> None:
        v = co._score({
            "variant_id": "v1", "launch_id": "l",
            "impressions": 1000, "clicks": 40, "orders": 4,
            "spend_usd": 20.0, "revenue_usd": 100.0,
        })
        self.assertAlmostEqual(v.ctr, 0.04)
        self.assertAlmostEqual(v.cvr, 0.1)
        self.assertAlmostEqual(v.cpa, 5.0)
        self.assertAlmostEqual(v.roas, 5.0)
        self.assertLess(v.roas_lower_95, v.roas)
        self.assertGreater(v.roas_upper_95, v.roas)


class TestOrchestrate(unittest.TestCase):
    def test_promotes_winner_and_prunes_loser(self) -> None:
        stats = [
            {"variant_id": "v1_hook", "launch_id": "a",
             "impressions": 2000, "clicks": 100, "orders": 20,
             "spend_usd": 50.0, "revenue_usd": 400.0},          # ROAS 8
            {"variant_id": "v2_benefits", "launch_id": "a",
             "impressions": 2000, "clicks": 40, "orders": 2,
             "spend_usd": 50.0, "revenue_usd": 40.0},           # ROAS 0.8
        ]
        report = co.orchestrate(stats)
        self.assertEqual(len(report.promotes), 1)
        self.assertEqual(report.promotes[0].variant_id, "v1_hook")
        self.assertEqual(len(report.prunes), 1)
        self.assertEqual(report.prunes[0].variant_id, "v2_benefits")
        # Refresh suggestion should pick an unused angle
        self.assertEqual(len(report.refresh_slots), 1)
        self.assertIn(report.refresh_slots[0]["replace_angle"],
                      {"hook", "benefits", "proof", "urgency", "comparison"})

    def test_single_variant_has_no_winner(self) -> None:
        stats = [{
            "variant_id": "v1", "launch_id": "a",
            "impressions": 5000, "clicks": 100, "orders": 10,
            "spend_usd": 100, "revenue_usd": 500,
        }]
        report = co.orchestrate(stats)
        self.assertEqual(report.promotes, [])
        self.assertEqual(report.prunes, [])

    def test_below_min_impressions_skipped(self) -> None:
        stats = [
            {"variant_id": "v1", "launch_id": "a",
             "impressions": 50, "clicks": 5, "orders": 1,
             "spend_usd": 10, "revenue_usd": 50},
            {"variant_id": "v2", "launch_id": "a",
             "impressions": 50, "clicks": 2, "orders": 0,
             "spend_usd": 10, "revenue_usd": 0},
        ]
        report = co.orchestrate(stats)
        self.assertEqual(report.promotes, [])

    def test_overlapping_intervals_hold(self) -> None:
        # Two variants with similar roas — intervals overlap → hold
        stats = [
            {"variant_id": "v1", "launch_id": "a",
             "impressions": 2000, "clicks": 100, "orders": 10,
             "spend_usd": 100, "revenue_usd": 400},
            {"variant_id": "v2", "launch_id": "a",
             "impressions": 2000, "clicks": 100, "orders": 11,
             "spend_usd": 100, "revenue_usd": 420},
        ]
        report = co.orchestrate(stats)
        self.assertEqual(len(report.promotes), 1)
        # The loser should be "hold" (overlapping CI), not prune
        losers = [v for v in report.variants
                  if v.verdict == "hold"]
        self.assertGreaterEqual(len(losers), 1)


class TestNextAngle(unittest.TestCase):
    def test_picks_unused(self) -> None:
        group = [
            co.VariantStats(variant_id="v1_hook", launch_id="a",
                            impressions=0, clicks=0, orders=0,
                            spend_usd=0, revenue_usd=0),
            co.VariantStats(variant_id="v2_benefits", launch_id="a",
                            impressions=0, clicks=0, orders=0,
                            spend_usd=0, revenue_usd=0),
        ]
        self.assertEqual(co._next_angle(group, "v1_hook"), "proof")


if __name__ == "__main__":
    unittest.main()
