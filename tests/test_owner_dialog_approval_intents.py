"""Owner-dialog intents for the Phase 2 approval queue.

Phrases tested:
  * "pending approvals" / "what's pending" → pending_approvals
  * "approve <16-hex>" → approve_request (auto-confirmed)
  * "deny <16-hex>" → deny_request
  * "deny <16-hex> reason words" → deny_request with reason
"""
from __future__ import annotations

import unittest

from agents.owner_dialog.tool_dispatcher import parse_intent


class TestPendingApprovalsIntent(unittest.TestCase):
    def _assert(self, text: str, tool: str):
        m = parse_intent(text)
        self.assertIsNotNone(m, msg=f"no match for {text!r}")
        self.assertEqual(m.tool, tool)

    def test_literal_phrases(self):
        for phrase in (
            "pending approvals",
            "pending requests",
            "pending approval",
            "what's pending",
            "whats pending",
            "approval queue",
        ):
            self._assert(phrase, "pending_approvals")


class TestApproveIntent(unittest.TestCase):
    def test_approve_with_hex_id(self):
        m = parse_intent("approve abc123def4567890")
        self.assertIsNotNone(m)
        self.assertEqual(m.tool, "approve_request")
        self.assertEqual(
            m.arguments["request_id"], "abc123def4567890",
        )

    def test_approve_auto_confirmed(self):
        """The word 'approve' itself is the confirmation —
        owner shouldn't also have to type 'confirm'."""
        m = parse_intent("approve abc123def4567890")
        self.assertTrue(m.confirmed)

    def test_approve_case_insensitive(self):
        m = parse_intent("APPROVE abc123def4567890")
        self.assertEqual(m.tool, "approve_request")

    def test_approve_short_id(self):
        """8-char min so we accept the truncated ID a rushed
        owner might copy-paste."""
        m = parse_intent("approve abc12345")
        self.assertIsNotNone(m)
        self.assertEqual(m.arguments["request_id"], "abc12345")

    def test_approve_without_id_no_match(self):
        """Bare 'approve' without a hex id should NOT trigger
        approve_request (could be a typo, want owner to see
        unambiguous failure)."""
        m = parse_intent("approve")
        # Might fall through to no-match, or match a different
        # intent. Either way the ID must not be fabricated.
        if m is not None and m.tool == "approve_request":
            self.fail("bare 'approve' should not match")


class TestDenyIntent(unittest.TestCase):
    def test_deny_basic(self):
        m = parse_intent("deny abc123def4567890")
        self.assertEqual(m.tool, "deny_request")
        self.assertEqual(
            m.arguments["request_id"], "abc123def4567890",
        )

    def test_deny_with_reason(self):
        m = parse_intent(
            "deny abc123def4567890 budget too aggressive",
        )
        self.assertEqual(m.tool, "deny_request")
        self.assertEqual(
            m.arguments["request_id"], "abc123def4567890",
        )
        self.assertEqual(
            m.arguments["reason"], "budget too aggressive",
        )

    def test_deny_auto_confirmed(self):
        m = parse_intent("deny abc123def4567890")
        self.assertTrue(m.confirmed)

    def test_deny_strips_trailing_confirm_word(self):
        """If owner types 'deny abc reason confirm' we should
        NOT include 'confirm' in the reason — it got stripped
        in the cleaned-text path."""
        m = parse_intent(
            "deny abc123def4567890 looks risky confirm",
        )
        self.assertEqual(m.tool, "deny_request")
        reason = m.arguments.get("reason", "")
        self.assertNotIn("confirm", reason.lower())


class TestCollisionSafety(unittest.TestCase):
    """Regression: approve/deny intents should not trigger for
    unrelated messages that happen to contain the words."""

    def test_conversational_approve_no_match(self):
        """Plain 'I approve of the plan' — no hex ID, so the
        strict pattern must not match approve_request."""
        m = parse_intent("I approve of the plan")
        if m is not None:
            self.assertNotEqual(m.tool, "approve_request")

    def test_approve_needs_hex_not_any_word(self):
        """Non-hex token after approve shouldn't match."""
        m = parse_intent("approve the budget")
        if m is not None:
            self.assertNotEqual(m.tool, "approve_request")


if __name__ == "__main__":
    unittest.main()
