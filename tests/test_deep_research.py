"""Tests for agents.research.deep_research — Track 7."""
from __future__ import annotations

import unittest

from agents.research.deep_research import (
    CompetitorPrice,
    DeepResearchAgent,
    DeepResearchReport,
    ReviewSummary,
    classify_review,
    extract_competitor_price,
    summarise_reviews,
)


class TestClassifyReview(unittest.TestCase):
    def test_positive_wins(self):
        label, defects = classify_review(
            "Great product, love it!",
        )
        self.assertEqual(label, "positive")
        self.assertEqual(defects, 0)

    def test_negative_wins(self):
        label, defects = classify_review(
            "It broke on arrival, poor quality, refund.",
        )
        self.assertEqual(label, "negative")
        self.assertGreaterEqual(defects, 1)

    def test_neutral_no_signals(self):
        label, _ = classify_review(
            "I bought this yesterday.",
        )
        self.assertEqual(label, "neutral")

    def test_mixed_signals_net_out(self):
        # 2 pos vs 1 neg → positive
        label, _ = classify_review(
            "Great quality but slow shipping.",
        )
        self.assertEqual(label, "positive")

    def test_empty_text(self):
        label, defects = classify_review("")
        self.assertEqual(label, "neutral")
        self.assertEqual(defects, 0)


class TestSummariseReviews(unittest.TestCase):
    def test_empty_reviews(self):
        s = summarise_reviews([])
        self.assertEqual(s.review_count, 0)
        self.assertEqual(s.sentiment_score, 0.5)

    def test_dict_and_string_shapes(self):
        reviews = [
            "Great quality",
            {"text": "Broken, refund requested"},
            {"text": "Neutral purchase"},
        ]
        s = summarise_reviews(reviews)
        self.assertEqual(s.review_count, 3)
        self.assertEqual(s.positive, 1)
        self.assertEqual(s.negative, 1)
        self.assertEqual(s.neutral, 1)

    def test_defect_rate_computed(self):
        reviews = (
            [{"text": "It broke on arrival"}] * 3
            + [{"text": "Great"}] * 7
        )
        s = summarise_reviews(reviews)
        self.assertAlmostEqual(
            s.defect_rate, 0.30, places=2,
        )

    def test_sample_snippets_capped(self):
        reviews = [
            {"text": f"Great! iteration {i}"}
            for i in range(10)
        ]
        s = summarise_reviews(
            reviews, sample_snippets=2,
        )
        self.assertEqual(len(s.sample_pos_snippets), 2)

    def test_sentiment_score(self):
        reviews = (
            [{"text": "Great"}] * 8
            + [{"text": "Terrible"}] * 2
        )
        s = summarise_reviews(reviews)
        self.assertAlmostEqual(
            s.sentiment_score, 0.8, places=2,
        )


class TestCompetitorPrice(unittest.TestCase):
    def test_extract_simple(self):
        cp = extract_competitor_price(
            source="amazon",
            url="https://amazon.com/dp/x",
            text="Buy now at $29.99 + free shipping",
        )
        self.assertIsNotNone(cp)
        self.assertEqual(cp.price, 29.99)

    def test_no_price_returns_none(self):
        cp = extract_competitor_price(
            source="amazon",
            url="https://x",
            text="Price varies",
        )
        self.assertIsNone(cp)

    def test_zero_price_rejected(self):
        cp = extract_competitor_price(
            source="amazon",
            url="https://x",
            text="Price $0.00 error",
        )
        self.assertIsNone(cp)

    def test_dict_round_trip(self):
        cp = CompetitorPrice(
            source="amazon",
            url="https://x",
            price=29.99,
        )
        self.assertIn("price", cp.as_dict())


class TestInvestigation(unittest.TestCase):
    def test_query_required(self):
        agent = DeepResearchAgent()
        with self.assertRaises(ValueError):
            agent.investigate("")

    def test_no_sources_returns_empty_report(self):
        agent = DeepResearchAgent()
        report = agent.investigate("pet feeder")
        self.assertIsNone(report.review_summary)
        self.assertEqual(report.competitor_prices, ())
        self.assertEqual(report.verdict, "inconclusive")

    def test_happy_path_with_mocked_sources(self):
        reviews = (
            [{"text": "Great quality"}] * 12
            + [{"text": "Slow shipping"}] * 2
        )
        hits = [
            {
                "source": "amazon",
                "url": "https://amazon.com/x",
                "snippet": "On sale $22.99",
            },
            {
                "source": "walmart",
                "url": "https://walmart.com/x",
                "snippet": "Walmart price $19.50",
            },
        ]
        agent = DeepResearchAgent(
            review_source=lambda q, limit: reviews,
            search_source=lambda q, limit: hits,
        )
        report = agent.investigate("pet slow feeder")
        self.assertIsNotNone(report.review_summary)
        self.assertEqual(
            report.review_summary.review_count, 14,
        )
        self.assertEqual(
            len(report.competitor_prices), 2,
        )
        self.assertGreater(
            report.median_competitor_price, 0,
        )

    def test_review_source_exception_surfaces_in_notes(self):
        def bad(q, limit):
            raise RuntimeError("net")
        agent = DeepResearchAgent(
            review_source=bad,
        )
        report = agent.investigate("q")
        self.assertTrue(
            any("review_source error" in n
                for n in report.notes),
        )

    def test_search_source_exception_handled(self):
        def bad(q, limit):
            raise RuntimeError("search 500")
        agent = DeepResearchAgent(
            search_source=bad,
        )
        report = agent.investigate("q")
        self.assertTrue(
            any("search_source error" in n
                for n in report.notes),
        )

    def test_verdict_avoid_defect_risk(self):
        reviews = (
            [{"text": "It broke on arrival"}] * 5
            + [{"text": "Great product"}] * 15
        )
        agent = DeepResearchAgent(
            review_source=lambda q, limit: reviews,
        )
        report = agent.investigate("q")
        self.assertEqual(
            report.verdict, "avoid_defect_risk",
        )

    def test_verdict_insufficient_reviews(self):
        reviews = [{"text": "Great"}] * 3
        agent = DeepResearchAgent(
            review_source=lambda q, limit: reviews,
        )
        report = agent.investigate("q")
        self.assertEqual(
            report.verdict, "insufficient_reviews",
        )

    def test_verdict_mixed_sentiment(self):
        reviews = (
            [{"text": "Great"}] * 10
            + [{"text": "Terrible"}] * 15
        )
        agent = DeepResearchAgent(
            review_source=lambda q, limit: reviews,
        )
        report = agent.investigate("q")
        self.assertEqual(report.verdict, "mixed_sentiment")

    def test_verdict_competitive_opportunity(self):
        reviews = (
            [{"text": "Great quality love it"}] * 20
        )
        hits = [{
            "source": "amazon",
            "url": "x",
            "snippet": "Price $30",
        }]
        agent = DeepResearchAgent(
            review_source=lambda q, limit: reviews,
            search_source=lambda q, limit: hits,
        )
        report = agent.investigate("q")
        self.assertEqual(
            report.verdict, "competitive_opportunity",
        )


class TestReportDict(unittest.TestCase):
    def test_dict_serialisable(self):
        report = DeepResearchReport(
            query="q",
            review_summary=ReviewSummary(
                review_count=5,
                positive=3,
                negative=1,
                neutral=1,
                defect_mentions=0,
            ),
            competitor_prices=(),
        )
        d = report.as_dict()
        self.assertIn("verdict", d)
        self.assertIn("review_summary", d)


if __name__ == "__main__":
    unittest.main()
