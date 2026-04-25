"""Social-proof aggregator — theme tagging + ranking tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain import social_proof as sp


class TestThemeTagging(unittest.TestCase):
    def test_single_theme(self) -> None:
        self.assertEqual(
            sp._tag_themes("Fast shipping, arrived in 3 days"),
            ["shipping"],
        )

    def test_multiple_themes(self) -> None:
        text = "Amazing quality and great value — I recommend it!"
        themes = sp._tag_themes(text)
        self.assertIn("quality", themes)
        self.assertIn("price", themes)
        self.assertIn("recommend", themes)

    def test_no_match_returns_empty(self) -> None:
        self.assertEqual(sp._tag_themes("just generic text"), [])


class TestQuoteSignal(unittest.TestCase):
    def test_longer_quote_higher_signal(self) -> None:
        short = sp.Quote(text="Great", stars=5, source="s")
        long_q = sp.Quote(
            text="Super-sturdy build and my kids love the colors." * 3,
            stars=5, source="s",
        )
        self.assertGreater(long_q.signal, short.signal)

    def test_multi_theme_higher(self) -> None:
        one = sp.Quote(text="t", stars=5, source="s",
                       themes=["quality"])
        many = sp.Quote(text="t", stars=5, source="s",
                        themes=["quality", "shipping", "design"])
        self.assertGreater(many.signal, one.signal)


class TestAggregate(unittest.TestCase):
    def test_empty_reviews_return_empty_pack(self) -> None:
        with patch.object(sp, "_load_reviews", return_value=[]):
            pack = sp.aggregate(product_id=1)
        self.assertEqual(pack.review_count, 0)
        self.assertEqual(pack.star_rating_avg, 0.0)

    def test_aggregates_themes_and_ranking(self) -> None:
        reviews = [
            {"text": "Fast shipping and great quality!",
             "stars": 5, "source": "judge_me"},
            {"text": "Beautiful design, love the color.",
             "stars": 4, "source": "loox"},
            {"text": "Support was super helpful.",
             "stars": 5, "source": "email"},
        ]
        with patch.object(sp, "_load_reviews", return_value=reviews):
            pack = sp.aggregate(product_id=1, top_k=3)
        self.assertEqual(pack.review_count, 3)
        self.assertAlmostEqual(pack.star_rating_avg, 14 / 3)
        self.assertIn("shipping", pack.themes)
        self.assertIn("quality", pack.themes)
        self.assertIn("design", pack.themes)
        self.assertIn("support", pack.themes)
        self.assertEqual(len(pack.top_quotes), 3)

    def test_top_k_respected(self) -> None:
        reviews = [
            {"text": f"Review {i} — great quality and design",
             "stars": 5, "source": "x"}
            for i in range(10)
        ]
        with patch.object(sp, "_load_reviews", return_value=reviews):
            pack = sp.aggregate(product_id=1, top_k=3)
        self.assertEqual(len(pack.top_quotes), 3)

    def test_missing_text_ignored(self) -> None:
        reviews = [
            {"text": "", "stars": 5, "source": "x"},
            {"text": "Legit and well-made.", "stars": 5, "source": "y"},
        ]
        with patch.object(sp, "_load_reviews", return_value=reviews):
            pack = sp.aggregate(product_id=1)
        self.assertEqual(pack.review_count, 1)


class TestRecordReview(unittest.TestCase):
    def test_record_returns_id(self) -> None:
        from unittest.mock import MagicMock
        fake_mi = MagicMock()
        fake_mi.create.return_value = 77
        fake_unified = MagicMock()
        fake_unified.get_memory_intelligence.return_value = fake_mi
        with patch("core.memory.unified_memory.get_unified_memory",
                   return_value=fake_unified):
            mid = sp.record_review(
                product_id=1, text="Great!", stars=5, source="judge_me",
            )
        self.assertEqual(mid, 77)
        fake_mi.create.assert_called_once()

    def test_record_swallows_exception(self) -> None:
        with patch("core.memory.unified_memory.get_unified_memory",
                   side_effect=RuntimeError("x")):
            mid = sp.record_review(1, "x", 5)
        self.assertEqual(mid, 0)


if __name__ == "__main__":
    unittest.main()
