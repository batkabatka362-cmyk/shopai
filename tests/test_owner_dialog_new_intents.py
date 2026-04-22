"""Owner-dialog dispatcher: new read-only intent coverage
(ready_for_live + live_health + rule_quality +
engine_feedback_stats + brain_module_catalog).

Each MCP tool the session shipped needs a natural-language
handle the owner can type from Telegram. These tests lock
the phrases so they don't drift.
"""
from __future__ import annotations

import unittest

from agents.owner_dialog.tool_dispatcher import parse_intent


class TestNewIntentPatterns(unittest.TestCase):
    def assert_dispatches_to(self, text: str, tool: str):
        m = parse_intent(text)
        self.assertIsNotNone(
            m, msg=f"no match for {text!r}",
        )
        self.assertEqual(
            m.tool, tool,
            msg=f"{text!r} → {m.tool}, expected {tool}",
        )

    def test_ready_for_live(self):
        for phrase in (
            "ready for live",
            "ready for live?",
            "are we ready for live",
            "go-live gate",
            "pre-t1",
            "can we go live",
            "can i go live",
        ):
            self.assert_dispatches_to(
                phrase, "ready_for_live",
            )

    def test_live_health(self):
        for phrase in (
            "live-health",
            "live health",
            "health trend",
            "how healthy",
        ):
            self.assert_dispatches_to(
                phrase, "live_health",
            )

    def test_rule_quality(self):
        for phrase in (
            "rule quality",
            "true positive rate",
            "true-positive rate",
            "rules lift",
            "lift",
        ):
            self.assert_dispatches_to(
                phrase, "rule_quality",
            )

    def test_engine_feedback(self):
        for phrase in (
            "engine feedback",
            "engine stats",
            "engine trend",
            "per-engine stats",
        ):
            self.assert_dispatches_to(
                phrase, "engine_feedback_stats",
            )

    def test_brain_module_catalog(self):
        for phrase in (
            "brain catalog",
            "brain modules",
            "module catalog",
        ):
            self.assert_dispatches_to(
                phrase, "brain_module_catalog",
            )

    def test_read_only_intents_dont_need_confirm(self):
        """None of these 5 tools are writes — the owner types
        the phrase without ``confirm`` and still gets a
        reply."""
        for phrase in (
            "ready for live",
            "live health",
            "rule quality",
            "engine stats",
            "brain catalog",
        ):
            m = parse_intent(phrase)
            self.assertIsNotNone(m)
            self.assertFalse(
                m.write,
                msg=f"{phrase!r} must be read-only",
            )


class TestExistingIntentsStillWork(unittest.TestCase):
    """Regression — previous session intents mustn't break."""

    def test_doctor(self):
        m = parse_intent("doctor")
        self.assertIsNotNone(m)
        self.assertEqual(m.tool, "doctor")

    def test_rulebook(self):
        m = parse_intent("rulebook")
        self.assertIsNotNone(m)
        self.assertEqual(m.tool, "list_rules")

    def test_autopilot_alive(self):
        m = parse_intent("is the daemon alive")
        self.assertIsNotNone(m)
        self.assertEqual(m.tool, "autopilot_status")


if __name__ == "__main__":
    unittest.main()
