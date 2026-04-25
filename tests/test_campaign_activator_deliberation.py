"""CampaignActivator → structured_decision wire-in tests.

Activation must produce a 5-pillar Deliberation record
without altering the verdict. Recorder failure is soft
(never blocks). Captures the existing gate truths into
constraint evaluations so audit trails survive without
duplicating policy.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.brain.structured_decision import (
    recent_deliberations,
    reset_recent_for_tests,
)
from execution.launch import campaign_activator as ca

# Reuse fakes from the existing activator test suite.
from tests.test_campaign_activator import (  # type: ignore[import]
    _activator,
    _green_crisis,
    _permissive_tripwire,
    _req,
    _FakeAds,
    _FakeConstraints,
    _FakeOutcomes,
    _FakeRationale,
    _FakeReadiness,
)


class TestDeliberationRecorded(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_activation_produces_one_deliberation(self):
        activator = _activator()
        result = activator.activate(_req())
        self.assertEqual(result.verdict, "dry_run")
        records = recent_deliberations(limit=10)
        self.assertEqual(len(records), 1)

    def test_outcome_carries_campaign_id(self):
        activator = _activator()
        activator.activate(_req(
            campaign_id="camp-foo-42",
        ))
        d = recent_deliberations()[0]
        self.assertIn("camp-foo-42", d.outcome.what)

    def test_value_usd_uses_weekly_budget(self):
        activator = _activator()
        activator.activate(_req(
            daily_budget_usd=20.0,
        ))
        d = recent_deliberations()[0]
        # 20/day × 7 days = 140
        self.assertAlmostEqual(
            d.outcome.value_usd, 140.0,
        )

    def test_two_directions_recorded(self):
        activator = _activator()
        activator.activate(_req())
        d = recent_deliberations()[0]
        labels = [x.label for x in d.directions]
        self.assertIn("activate", labels)
        self.assertIn("hold", labels)

    def test_chosen_direction_is_activate(self):
        activator = _activator()
        activator.activate(_req())
        d = recent_deliberations()[0]
        self.assertIsNotNone(d.decision)
        self.assertEqual(d.decision.label, "activate")

    def test_constraints_capture_pipeline_steps(self):
        activator = _activator()
        activator.activate(_req())
        d = recent_deliberations()[0]
        constraint_names = {c.name for c in d.constraints}
        # The pipeline writes each gate to steps; the
        # recorder lifts each into a constraint.
        for expected in (
            "crisis", "preflight", "tripwire",
            "readiness",
        ):
            self.assertIn(expected, constraint_names)

    def test_awareness_marks_money_path(self):
        activator = _activator()
        activator.activate(_req())
        d = recent_deliberations()[0]
        self.assertEqual(
            d.awareness.dollar_distance, 0,
        )
        self.assertEqual(
            d.awareness.loop_check, "aligned",
        )
        self.assertEqual(
            d.awareness.plumbing_vs_capability,
            "capability",
        )


class TestSoftFailIsolation(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_recorder_failure_does_not_block(self):
        """If structured_decision raises, the activation
        verdict must be unchanged."""
        activator = _activator()
        with patch(
            "core.brain.structured_decision.deliberate",
            side_effect=RuntimeError("recorder down"),
        ):
            result = activator.activate(_req())
        # Verdict still produced
        self.assertEqual(result.verdict, "dry_run")
        # No record persisted (deliberate raised before record)
        self.assertEqual(
            len(recent_deliberations()), 0,
        )

    def test_record_failure_does_not_block(self):
        activator = _activator()
        with patch(
            "core.brain.structured_decision.record_deliberation",
            side_effect=RuntimeError("disk full"),
        ):
            result = activator.activate(_req())
        self.assertEqual(result.verdict, "dry_run")


class TestVerdictUnchanged(unittest.TestCase):
    """Behavior parity: every existing activator outcome
    stays identical with the recorder wired in."""

    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_dry_run_default(self):
        activator = _activator()
        result = activator.activate(_req())
        self.assertEqual(result.verdict, "dry_run")

    def test_blocked_when_crisis_red(self):
        crisis = MagicMock()
        crisis.detect_state.return_value = MagicMock(
            level="red", halted=True, reason="storm",
        )
        activator = _activator(crisis_responder=crisis)
        result = activator.activate(_req())
        self.assertEqual(result.verdict, "blocked")
        # Recorder did NOT fire — the activation aborted
        # before the record point. Audit trail remains
        # consistent: only successful pipelines record.
        self.assertEqual(
            len(recent_deliberations()), 0,
        )


class TestMcpSurface(unittest.TestCase):
    """End-to-end: activation → MCP recent_deliberations
    surfaces the record."""

    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_mcp_returns_record(self):
        activator = _activator()
        activator.activate(_req())
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        reg = build_default_registry()
        res = reg.call(ToolCall(
            tool="recent_deliberations",
            arguments={"limit": 5},
        ))
        self.assertTrue(res.ok)
        self.assertGreaterEqual(
            res.content["count"], 1,
        )
        first = res.content["deliberations"][0]
        self.assertIn(
            "outcome", first,
        )
        self.assertIn(
            "activate campaign",
            first["outcome"]["what"],
        )


if __name__ == "__main__":
    unittest.main()
