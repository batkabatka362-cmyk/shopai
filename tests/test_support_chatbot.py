"""Tests for agents.customer.support_chatbot — LX.1 first-line."""
from __future__ import annotations

import unittest

from agents.customer.support_chatbot import (
    SupportAnswer,
    SupportChatbot,
    SupportRule,
)


class TestRulesetDefault(unittest.TestCase):
    def test_default_rules_loaded(self):
        bot = SupportChatbot()
        ids = {r.rule_id for r in bot.rules()}
        # Sanity check — presence of the core 12
        self.assertIn("shipping_time", ids)
        self.assertIn("refund_request", ids)
        self.assertIn("damaged_defective", ids)
        self.assertIn("cancel_order", ids)
        self.assertIn("change_address", ids)


class TestAnswering(unittest.TestCase):
    def setUp(self):
        self.bot = SupportChatbot()

    def test_blank_question_escalates(self):
        a = self.bot.answer("")
        self.assertEqual(a.verdict, "escalate")
        self.assertIn("empty", a.escalate_reason)

    def test_shipping_time_question(self):
        a = self.bot.answer(
            "How long until my order will arrive?",
        )
        self.assertEqual(a.verdict, "answered")
        self.assertIn("shipping_time", a.matched_rules)
        self.assertIn("7-15", a.text)

    def test_refund_question(self):
        a = self.bot.answer(
            "I want a refund for my order.",
        )
        self.assertEqual(a.verdict, "answered")
        self.assertEqual(a.kind, "refund")
        self.assertIn("refund", a.text.lower())

    def test_damaged_item_weighted_above_refund(self):
        # "damaged" should win even when "refund" also matches
        a = self.bot.answer(
            "My item arrived damaged, can I get a refund?",
        )
        self.assertEqual(a.verdict, "answered")
        self.assertEqual(a.matched_rules[0], "damaged_defective")

    def test_cancel_order(self):
        a = self.bot.answer("Cancel my order please.")
        self.assertEqual(a.verdict, "answered")
        self.assertEqual(a.kind, "order_status")

    def test_customs_duties(self):
        a = self.bot.answer(
            "Do I have to pay customs duties?",
        )
        self.assertEqual(a.verdict, "answered")
        self.assertEqual(a.kind, "shipping")

    def test_unmatched_escalates(self):
        a = self.bot.answer(
            "Please recite Shakespeare to me.",
        )
        self.assertEqual(a.verdict, "escalate")
        self.assertIn("no matching", a.escalate_reason)

    def test_contact_human_rule(self):
        a = self.bot.answer(
            "Can I speak to a human agent?",
        )
        self.assertEqual(a.verdict, "answered")
        self.assertIn("contact", a.matched_rules)


class TestRuleManagement(unittest.TestCase):
    def setUp(self):
        self.bot = SupportChatbot(rules=[])

    def test_add_rule_and_match(self):
        self.bot.add_rule(SupportRule(
            rule_id="custom",
            pattern=r"\bclearance\b",
            answer="Clearance items are final sale.",
            kind="faq",
        ))
        a = self.bot.answer("Is the clearance final?")
        self.assertEqual(a.verdict, "answered")
        self.assertIn("custom", a.matched_rules)

    def test_add_rule_blank_id_raises(self):
        with self.assertRaises(ValueError):
            self.bot.add_rule(SupportRule(
                rule_id="",
                pattern="x",
                answer="y",
            ))

    def test_add_rule_bad_regex_raises(self):
        with self.assertRaises(ValueError):
            self.bot.add_rule(SupportRule(
                rule_id="bad",
                pattern="[unclosed",
                answer="x",
            ))

    def test_remove_rule(self):
        self.bot.add_rule(SupportRule(
            rule_id="x",
            pattern="x",
            answer="x",
        ))
        self.assertTrue(self.bot.remove_rule("x"))
        self.assertFalse(self.bot.remove_rule("x"))

    def test_empty_ruleset_escalates_everything(self):
        a = self.bot.answer("anything")
        self.assertEqual(a.verdict, "escalate")


class TestConfidence(unittest.TestCase):
    def test_high_floor_promotes_escalation(self):
        bot = SupportChatbot(
            escalate_confidence_floor=0.99,
        )
        # Multi-match question → top rule is <99% of weights
        a = bot.answer(
            "My item arrived damaged, can I get a refund? "
            "Where is my order?",
        )
        self.assertEqual(a.verdict, "escalate")

    def test_zero_floor_allows_even_weak(self):
        bot = SupportChatbot(
            escalate_confidence_floor=0.0,
        )
        a = bot.answer("shipping time?")
        self.assertEqual(a.verdict, "answered")

    def test_bad_floor_raises(self):
        with self.assertRaises(ValueError):
            SupportChatbot(escalate_confidence_floor=1.5)


class TestAnswerDict(unittest.TestCase):
    def test_answer_as_dict_serialisable(self):
        bot = SupportChatbot()
        a = bot.answer("shipping time?")
        d = a.as_dict()
        self.assertIn("verdict", d)
        self.assertIn("matched_rules", d)


class TestStats(unittest.TestCase):
    def test_stats_shape(self):
        bot = SupportChatbot()
        s = bot.stats()
        self.assertGreater(s["rule_count"], 0)
        self.assertIn("refund_request", s["rules"])


if __name__ == "__main__":
    unittest.main()
