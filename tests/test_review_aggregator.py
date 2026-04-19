"""Review aggregator tests."""
from __future__ import annotations

import time
import unittest

from core.brain import review_aggregator as ra


class TestSources(unittest.TestCase):
    def test_declare_source(self) -> None:
        a = ra.ReviewAggregator()
        a.add_source("judge_me", scale_max=5)
        self.assertEqual(a.sources()["judge_me"], 5.0)

    def test_blank_source_raises(self) -> None:
        a = ra.ReviewAggregator()
        with self.assertRaises(ValueError):
            a.add_source("", 5)

    def test_zero_scale_raises(self) -> None:
        a = ra.ReviewAggregator()
        with self.assertRaises(ValueError):
            a.add_source("x", 0)

    def test_ingest_undeclared_source_raises(self) -> None:
        a = ra.ReviewAggregator()
        with self.assertRaises(KeyError):
            a.ingest("unknown", [])


class TestIngest(unittest.TestCase):
    def setUp(self) -> None:
        self.a = ra.ReviewAggregator()
        self.a.add_source("judge_me", 5)
        self.a.add_source("loox_10pt", 10)

    def test_normalises_5_scale(self) -> None:
        self.a.ingest("judge_me", [{
            "product_id": "p1", "stars": 5,
            "customer_id": "c1", "body": "great",
        }])
        reviews = self.a.for_product("p1")
        self.assertEqual(reviews[0].stars, 5.0)

    def test_normalises_10_scale_to_5(self) -> None:
        self.a.ingest("loox_10pt", [{
            "product_id": "p2", "rating": 8,
            "customer_id": "c2", "body": "good",
        }])
        reviews = self.a.for_product("p2")
        self.assertAlmostEqual(reviews[0].stars, 4.0)

    def test_missing_product_id_skipped(self) -> None:
        self.a.ingest("judge_me", [{
            "stars": 5, "body": "x", "customer_id": "c",
        }])
        self.assertEqual(len(self.a._reviews), 0)

    def test_dedup_across_sources(self) -> None:
        rec = {
            "product_id": "p", "customer_id": "c",
            "body": "Great product!",
            "stars": 5, "created_at": 1_700_000_000,
        }
        n1 = self.a.ingest("judge_me", [rec])
        n2 = self.a.ingest("loox_10pt", [
            {**rec, "rating": 10},
        ])
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)

    def test_stars_out_of_range_clamped(self) -> None:
        self.a.ingest("judge_me", [{
            "product_id": "p",
            "stars": 10, "body": "x", "customer_id": "c",
        }])
        r = self.a.for_product("p")[0]
        self.assertLessEqual(r.stars, 5.0)

    def test_iso_timestamp_parsed(self) -> None:
        self.a.ingest("judge_me", [{
            "product_id": "p", "stars": 5,
            "customer_id": "c", "body": "x",
            "created_at": "2024-01-15T12:00:00Z",
        }])
        r = self.a.for_product("p")[0]
        self.assertGreater(r.created_at, 0)


class TestAggregate(unittest.TestCase):
    def setUp(self) -> None:
        self.a = ra.ReviewAggregator()
        self.a.add_source("judge_me", 5)
        self.a.ingest("judge_me", [
            {"product_id": "p", "stars": 5, "customer_id": f"c{i}",
             "body": f"review {i}"}
            for i in range(5)
        ])
        self.a.ingest("judge_me", [
            {"product_id": "p", "stars": 1, "customer_id": "bad",
             "body": "terrible"},
        ])

    def test_averages(self) -> None:
        stats = self.a.aggregate("p")
        self.assertEqual(stats.count, 6)
        self.assertAlmostEqual(stats.avg_stars, (5 * 5 + 1) / 6, places=2)

    def test_unknown_product_empty(self) -> None:
        stats = self.a.aggregate("never_seen")
        self.assertEqual(stats.count, 0)

    def test_low_and_high_counts(self) -> None:
        stats = self.a.aggregate("p")
        self.assertEqual(stats.high_count, 5)
        self.assertEqual(stats.low_count, 1)


class TestSentimentFlagged(unittest.TestCase):
    def test_flags_products_with_too_many_lows(self) -> None:
        a = ra.ReviewAggregator()
        a.add_source("src", 5)
        for i in range(5):
            a.ingest("src", [{
                "product_id": "bad", "stars": 1,
                "customer_id": f"c{i}", "body": f"bad {i}",
            }])
        a.ingest("src", [{
            "product_id": "good", "stars": 5,
            "customer_id": "x", "body": "great",
        }] * 5)
        flagged = a.sentiment_flagged(min_reviews=3, low_ratio=0.5)
        product_ids = [s.product_id for s in flagged]
        self.assertIn("bad", product_ids)
        self.assertNotIn("good", product_ids)


class TestFakeDetection(unittest.TestCase):
    def test_coordinated_body_flagged(self) -> None:
        a = ra.ReviewAggregator()
        a.add_source("src", 5)
        # 3 different customers, identical body — fake ring
        for i in range(3):
            a.ingest("src", [{
                "product_id": "p",
                "customer_id": f"c{i}",
                "stars": 5,
                "body": "Best product ever!!!",
            }])
        fakes = a.detect_fakes(min_body_match=3)
        self.assertTrue(fakes)

    def test_unique_bodies_not_flagged(self) -> None:
        a = ra.ReviewAggregator()
        a.add_source("src", 5)
        for i in range(5):
            a.ingest("src", [{
                "product_id": "p",
                "customer_id": f"c{i}",
                "stars": 5,
                "body": f"Unique review {i} with distinct words",
            }])
        fakes = a.detect_fakes(min_body_match=2)
        self.assertEqual(fakes, [])


class TestReset(unittest.TestCase):
    def test_reset_clears(self) -> None:
        a = ra.ReviewAggregator()
        a.add_source("src", 5)
        a.ingest("src", [{"product_id": "p", "stars": 5,
                           "customer_id": "c", "body": "x"}])
        a.reset()
        self.assertEqual(a.stats()["total_reviews"], 0)


if __name__ == "__main__":
    unittest.main()
