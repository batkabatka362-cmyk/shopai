"""Query rewriter tests."""
from __future__ import annotations

import unittest

from core.brain import query_rewriter as qr


class TestPrice(unittest.TestCase):
    def setUp(self) -> None:
        self.r = qr.QueryRewriter()

    def test_under_price_extracted(self) -> None:
        res = self.r.rewrite("under $50 headphones")
        self.assertEqual(res.filters.get("price_max"), 50.0)

    def test_over_price_extracted(self) -> None:
        res = self.r.rewrite("speakers over $200")
        self.assertEqual(res.filters.get("price_min"), 200.0)

    def test_range(self) -> None:
        res = self.r.rewrite("products between $20 to $50")
        self.assertEqual(res.filters.get("price_min"), 20.0)
        self.assertEqual(res.filters.get("price_max"), 50.0)

    def test_cheap_keyword(self) -> None:
        res = self.r.rewrite("cheap headphones")
        self.assertEqual(res.filters.get("price_band"), "impulse")

    def test_premium_keyword(self) -> None:
        res = self.r.rewrite("premium speakers")
        self.assertEqual(res.filters.get("price_band"), "premium")


class TestNiche(unittest.TestCase):
    def test_audio_detected(self) -> None:
        res = qr.QueryRewriter().rewrite("wireless headphones")
        self.assertEqual(res.filters.get("niche"), "audio")

    def test_fashion_detected(self) -> None:
        res = qr.QueryRewriter().rewrite("summer dress collection")
        self.assertEqual(res.filters.get("niche"), "fashion")

    def test_no_niche_known(self) -> None:
        res = qr.QueryRewriter().rewrite("random thing")
        self.assertNotIn("niche", res.filters)


class TestRating(unittest.TestCase):
    def test_stars_number(self) -> None:
        res = qr.QueryRewriter().rewrite("4 star products")
        self.assertEqual(res.filters.get("min_stars"), 4)

    def test_stars_plus(self) -> None:
        res = qr.QueryRewriter().rewrite("5+ rated")
        self.assertEqual(res.filters.get("min_stars"), 5)

    def test_good_reviews_phrase(self) -> None:
        res = qr.QueryRewriter().rewrite("items with good reviews")
        self.assertEqual(res.filters.get("min_stars"), 4)


class TestDate(unittest.TestCase):
    def setUp(self) -> None:
        self.r = qr.QueryRewriter()

    def test_last_n_days(self) -> None:
        res = self.r.rewrite("orders last 7 days")
        self.assertIn("since_ts", res.filters)

    def test_last_month(self) -> None:
        res = self.r.rewrite("orders from last month")
        self.assertIn("since_ts", res.filters)

    def test_today(self) -> None:
        res = self.r.rewrite("today's events")
        self.assertIn("since_ts", res.filters)


class TestTerms(unittest.TestCase):
    def test_clean_terms_stripped_of_filters(self) -> None:
        res = qr.QueryRewriter().rewrite(
            "cheap audio headphones under $50",
        )
        # price + cheap + audio keyword extracted → residual is just
        # the unknown remainder.
        self.assertNotIn("cheap", res.terms.lower())
        self.assertNotIn("under", res.terms.lower())

    def test_empty_query(self) -> None:
        res = qr.QueryRewriter().rewrite("")
        self.assertEqual(res.terms, "")
        self.assertEqual(res.confidence, 0.0)


class TestConfidence(unittest.TestCase):
    def test_fully_parseable_query_high_confidence(self) -> None:
        res = qr.QueryRewriter().rewrite("cheap audio under $50")
        self.assertGreater(res.confidence, 0.4)

    def test_garbage_query_low_confidence(self) -> None:
        res = qr.QueryRewriter().rewrite(
            "xyz uncategorised random phrase",
        )
        self.assertLess(res.confidence, 0.5)


class TestSuggestions(unittest.TestCase):
    def test_canonical_suggestion(self) -> None:
        res = qr.QueryRewriter().rewrite(
            "premium audio headphones",
        )
        self.assertTrue(res.suggestions)
        combined = res.suggestions[0]
        self.assertIn("audio", combined)
        self.assertIn("premium", combined)


class TestCustomExtractor(unittest.TestCase):
    def test_register_extractor(self) -> None:
        r = qr.QueryRewriter()
        def gift(query):
            if "gift" in query.lower():
                return {"gift": True}, ["gift"]
            return {}, []
        r.register_extractor(gift)
        res = r.rewrite("nice gift for mom")
        self.assertTrue(res.filters.get("gift"))


class TestAsDict(unittest.TestCase):
    def test_result_as_dict(self) -> None:
        res = qr.QueryRewriter().rewrite("audio under $50")
        d = res.as_dict()
        for key in ("terms", "filters", "suggestions",
                     "confidence", "raw_query"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
