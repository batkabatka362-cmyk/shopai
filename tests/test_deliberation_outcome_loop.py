"""Refine + learn loop tests — Deliberation back-fill from
order webhook (CLAUDE.md §4d pillar 4 / §4b/B closed-loop
telemetry).

Pre-this-commit: Deliberations were write-once snapshots.
A purchase event flowed through OutcomeRecorder + engine
bus + agentic attribution but never touched the structured
record that DROVE the decision. Owner couldn't see
predicted-vs-observed for the 5-pillar reasoning.

After: every paid order with ``shopai_decision_id`` in
note_attributes back-fills the matching Deliberation
with the measured revenue + items. Owner inspects via
MCP recent_deliberations and sees the prediction +
the actual data side by side.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.brain.structured_decision import (
    Constraint,
    Deliberation,
    OutcomeSpec,
    SelfAwareness,
    ThinkingDirection,
    deliberate,
    find_deliberation_by_decision_id,
    record_deliberation,
    record_outcome_for_decision,
    recent_deliberations,
    reset_recent_for_tests,
)
from core.webhooks.order_handler import (
    OrderWebhookHandler,
)


def _seeded_deliberation(
    decision_id: str,
    expected_value: float = 50.0,
) -> Deliberation:
    d = deliberate(
        outcome=OutcomeSpec(
            what="activate test",
            why="seed",
            measurable="ROAS≥1.5",
            value_usd=expected_value,
        ),
        directions=[
            ThinkingDirection(
                label="activate",
                action={"campaign_id": "c-1"},
                reasoning="r",
                expected_value=expected_value,
                confidence=0.8,
            ),
        ],
        constraints=[
            Constraint(
                name="ok", kind="hard", reason="r",
            ),
        ],
        awareness=SelfAwareness(
            loop_check="aligned",
            dollar_distance=0,
            plumbing_vs_capability="capability",
        ),
    )
    d.decision_id = decision_id
    record_deliberation(d)
    return d


# ── Module API: record_outcome_for_decision ──────────────


class TestBackFillFunction(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_back_fills_when_match_exists(self):
        d = _seeded_deliberation("dec-1")
        ok = record_outcome_for_decision(
            "dec-1",
            {"revenue_usd": 99.50, "items": 2},
        )
        self.assertTrue(ok)
        self.assertEqual(d.observation["items"], 2)
        self.assertGreater(d.observed_ts, 0)

    def test_returns_false_when_unknown_id(self):
        ok = record_outcome_for_decision(
            "missing-dec",
            {"revenue_usd": 1.0},
        )
        self.assertFalse(ok)

    def test_blank_id_rejected(self):
        ok = record_outcome_for_decision(
            "", {"revenue_usd": 1.0},
        )
        self.assertFalse(ok)

    def test_non_dict_observation_rejected(self):
        _seeded_deliberation("dec-x")
        ok = record_outcome_for_decision(
            "dec-x", "not a dict",  # type: ignore[arg-type]
        )
        self.assertFalse(ok)

    def test_most_recent_match_wins(self):
        # Two records under the same id — back-fill the
        # newest so re-decisions don't lose data.
        _seeded_deliberation("dup")
        d2 = _seeded_deliberation(
            "dup", expected_value=200.0,
        )
        record_outcome_for_decision(
            "dup", {"revenue_usd": 1.0},
        )
        self.assertEqual(
            d2.observation.get("revenue_usd"), 1.0,
        )

    def test_lookup_helper_returns_match(self):
        d = _seeded_deliberation("look-1")
        found = find_deliberation_by_decision_id("look-1")
        self.assertIs(found, d)

    def test_lookup_unknown_returns_none(self):
        self.assertIsNone(
            find_deliberation_by_decision_id("missing"),
        )


# ── Webhook → back-fill end-to-end ───────────────────────


def _order(decision_id: str, revenue: str = "29.99"):
    return {
        "id": "ord-1",
        "total_price": revenue,
        "subtotal_price": revenue,
        "line_items": [{"sku": "s-1", "quantity": 1}],
        "customer": {"id": "c-1"},
        "note_attributes": [
            {
                "name": "shopai_decision_id",
                "value": decision_id,
            },
        ],
    }


class TestWebhookBackFill(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_paid_order_back_fills_deliberation(self):
        d = _seeded_deliberation("dec-paid-1")
        h = OrderWebhookHandler()
        result = h.handle_order_paid(
            _order("dec-paid-1", revenue="42.00"),
        )
        self.assertTrue(
            result.get("deliberation_observed"),
        )
        self.assertEqual(
            d.observation.get("kind"), "purchase",
        )
        self.assertAlmostEqual(
            d.observation.get("revenue_usd"), 42.0,
        )
        self.assertEqual(
            d.observation.get("order_id"), "ord-1",
        )

    def test_unknown_decision_id_returns_false(self):
        h = OrderWebhookHandler()
        result = h.handle_order_paid(
            _order("dec-not-seeded"),
        )
        self.assertFalse(
            result.get("deliberation_observed"),
        )

    def test_no_decision_id_skips_back_fill(self):
        order = _order("dec-x")
        order["note_attributes"] = []
        h = OrderWebhookHandler()
        result = h.handle_order_paid(order)
        self.assertNotIn(
            "deliberation_observed", result,
        )

    def test_back_fill_failure_does_not_crash(self):
        _seeded_deliberation("dec-2")
        h = OrderWebhookHandler()
        with patch(
            "core.brain.structured_decision."
            "record_outcome_for_decision",
            side_effect=RuntimeError("ledger broken"),
        ):
            result = h.handle_order_paid(_order("dec-2"))
        # webhook still succeeds
        self.assertEqual(
            result.get("order_id"), "ord-1",
        )
        self.assertFalse(
            result.get("deliberation_observed"),
        )

    def test_agentic_channel_propagates(self):
        d = _seeded_deliberation("dec-agentic")
        order = _order("dec-agentic")
        order["source_name"] = "chatgpt"
        h = OrderWebhookHandler()
        h.handle_order_paid(order)
        self.assertEqual(
            d.observation.get("agentic_channel"),
            "chatgpt",
        )


# ── as_dict round-trip with new fields ───────────────────


class TestAsDict(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_round_trip_includes_new_fields(self):
        d = _seeded_deliberation("dec-as-dict")
        record_outcome_for_decision(
            "dec-as-dict",
            {"revenue_usd": 10.0},
        )
        payload = d.as_dict()
        self.assertEqual(
            payload["decision_id"], "dec-as-dict",
        )
        self.assertIn("observation", payload)
        self.assertEqual(
            payload["observation"]["revenue_usd"], 10.0,
        )
        self.assertGreater(payload["observed_ts"], 0)


# ── MCP surface ──────────────────────────────────────────


class TestMcpVisibility(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_observation_visible_via_mcp(self):
        d = _seeded_deliberation("dec-mcp")
        record_outcome_for_decision(
            "dec-mcp",
            {"revenue_usd": 88.0},
        )
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="recent_deliberations",
        ))
        self.assertTrue(res.ok)
        first = res.content["deliberations"][0]
        self.assertEqual(
            first["decision_id"], "dec-mcp",
        )
        self.assertEqual(
            first["observation"]["revenue_usd"], 88.0,
        )


if __name__ == "__main__":
    unittest.main()
