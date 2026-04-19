"""Sentiment + intent analyser tests."""
from __future__ import annotations

import unittest

from core.brain import sentiment as s


class TestSentiment(unittest.TestCase):
    def test_positive_text(self) -> None:
        out = s.analyse("I love this product, amazing quality!")
        self.assertGreater(out.sentiment_score, 0.3)
        self.assertEqual(out.sentiment_label, "positive")

    def test_negative_text(self) -> None:
        out = s.analyse("Terrible experience, worst purchase ever.")
        self.assertLess(out.sentiment_score, -0.3)
        self.assertEqual(out.sentiment_label, "negative")

    def test_neutral_text(self) -> None:
        out = s.analyse("The package arrived today.")
        self.assertEqual(out.sentiment_label, "neutral")

    def test_negation_flips_sentiment(self) -> None:
        out = s.analyse("not great, really terrible")
        self.assertLess(out.sentiment_score, 0)

    def test_empty_text(self) -> None:
        out = s.analyse("")
        self.assertEqual(out.sentiment_label, "neutral")
        self.assertEqual(out.intent, "other")


class TestIntent(unittest.TestCase):
    def test_complaint(self) -> None:
        self.assertEqual(
            s.intent("product arrived broken, need a refund"),
            "complaint",
        )

    def test_question(self) -> None:
        self.assertEqual(
            s.intent("How do I reset my password?"),
            "question",
        )

    def test_praise(self) -> None:
        self.assertEqual(
            s.intent("I love it, highly recommend"),
            "praise",
        )

    def test_purchase_intent(self) -> None:
        self.assertEqual(
            s.intent("how much for the blue one?"),
            "purchase_intent",
        )

    def test_unsubscribe(self) -> None:
        self.assertEqual(
            s.intent("please unsubscribe me from your list"),
            "unsubscribe",
        )

    def test_request(self) -> None:
        self.assertEqual(
            s.intent("please send me a new shipping label"),
            "request",
        )

    def test_unknown_returns_other(self) -> None:
        self.assertEqual(s.intent("Generic filler text"), "other")


class TestUrgency(unittest.TestCase):
    def test_refund_is_high(self) -> None:
        self.assertEqual(s.urgency("need a refund asap"), 3)

    def test_soon_is_one(self) -> None:
        self.assertEqual(s.urgency("please ship soon"), 1)

    def test_nothing_is_zero(self) -> None:
        self.assertEqual(s.urgency("hey how are you"), 0)


class TestEmotion(unittest.TestCase):
    def test_joy(self) -> None:
        self.assertEqual(s.emotion("I'm so happy and delighted"), "joy")

    def test_anger(self) -> None:
        self.assertEqual(s.emotion("I am furious about this"), "anger")

    def test_fallback_neutral(self) -> None:
        self.assertEqual(s.emotion("package delivered"), "neutral")


class TestAnalyse(unittest.TestCase):
    def test_complaint_sadness_high_urgency(self) -> None:
        out = s.analyse(
            "I am extremely disappointed — product arrived broken. "
            "I need a refund asap."
        )
        self.assertEqual(out.intent, "complaint")
        self.assertEqual(out.urgency, 3)
        self.assertIn(out.emotion, {"sadness", "anger"})
        self.assertEqual(out.sentiment_label, "negative")

    def test_positive_buy_intent(self) -> None:
        out = s.analyse("I love the red one — how much? I want to buy it!")
        self.assertEqual(out.intent, "purchase_intent")
        self.assertEqual(out.sentiment_label, "positive")
        self.assertEqual(out.emotion, "joy")


if __name__ == "__main__":
    unittest.main()
