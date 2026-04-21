"""PublisherBundle → structured_decision wire-in tests.

Mirror of test_campaign_activator_deliberation: launch must
produce a 5-pillar Deliberation record without altering the
verdict. Soft-fail on recorder errors. Audit constraints
capture each pipeline step.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.brain.structured_decision import (
    recent_deliberations,
    reset_recent_for_tests,
)
from execution.launch import publisher_bundle as pb

# Reuse fakes from the existing publisher test suite.
from tests.test_publisher_bundle import (  # type: ignore[import]
    _FakeAds,
    _FakeContent,
    _FakeOutcomes,
    _FakeProducts,
    _FakeRationale,
    _request,
)


def _bundle(**overrides):
    defaults = dict(
        content_generator=_FakeContent(),
        product_creator=_FakeProducts(),
        ad_adapter=_FakeAds(),
        outcome_recorder=_FakeOutcomes(),
        rationale_builder=_FakeRationale(),
    )
    defaults.update(overrides)
    return pb.PublisherBundle(**defaults)


class TestDeliberationRecorded(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_launch_produces_one_deliberation(self):
        bundle = _bundle()
        result = bundle.launch(_request())
        self.assertTrue(result.ok)
        records = recent_deliberations(limit=10)
        self.assertEqual(len(records), 1)

    def test_outcome_carries_product_title(self):
        bundle = _bundle()
        bundle.launch(_request())
        d = recent_deliberations()[0]
        self.assertIn(
            "Pet Slow-Feeder Bowl", d.outcome.what,
        )

    def test_value_usd_uses_weekly_budget(self):
        bundle = _bundle()
        bundle.launch(_request(ad_budget_daily=20.0))
        d = recent_deliberations()[0]
        # 20/day × 7 = 140
        self.assertAlmostEqual(d.outcome.value_usd, 140.0)

    def test_two_directions_recorded(self):
        bundle = _bundle()
        bundle.launch(_request())
        d = recent_deliberations()[0]
        labels = [x.label for x in d.directions]
        self.assertIn("launch", labels)
        self.assertIn("defer", labels)

    def test_chosen_direction_is_launch(self):
        bundle = _bundle()
        bundle.launch(_request())
        d = recent_deliberations()[0]
        self.assertIsNotNone(d.decision)
        self.assertEqual(d.decision.label, "launch")

    def test_constraints_capture_pipeline_steps(self):
        bundle = _bundle()
        bundle.launch(_request())
        d = recent_deliberations()[0]
        names = {c.name for c in d.constraints}
        # Generated copy + product creation + EU compliance
        # always run; video_generate may or may not appear
        # depending on opt-in gate.
        self.assertIn("generate_copy", names)
        self.assertIn("create_product", names)
        self.assertIn("eu_ai_compliance", names)

    def test_awareness_marks_money_path(self):
        bundle = _bundle()
        bundle.launch(_request())
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

    def test_deliberate_failure_does_not_block(self):
        bundle = _bundle()
        with patch(
            "core.brain.structured_decision.deliberate",
            side_effect=RuntimeError("recorder down"),
        ):
            result = bundle.launch(_request())
        # Launch still succeeds
        self.assertTrue(result.ok)
        self.assertEqual(
            len(recent_deliberations()), 0,
        )

    def test_record_failure_does_not_block(self):
        bundle = _bundle()
        with patch(
            "core.brain.structured_decision"
            ".record_deliberation",
            side_effect=RuntimeError("disk full"),
        ):
            result = bundle.launch(_request())
        self.assertTrue(result.ok)


class TestEarlyAbortDoesNotRecord(unittest.TestCase):
    """Pre-recorder failures (copy / product creation) abort
    before the recorder slot — record set stays clean."""

    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_failed_product_create_no_record(self):
        # Match existing test_product_creation_failure_aborts —
        # live=True + SHOPAI_ENABLE_LIVE_EXECUTION=1 trigger
        # the real error path. Dry-run shortcuts the call.
        import os
        orig = os.environ.get(
            "SHOPAI_ENABLE_LIVE_EXECUTION",
        )
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"
        try:
            bundle = _bundle(
                product_creator=_FakeProducts(
                    status="error",
                ),
            )
            result = bundle.launch(_request(live=True))
        finally:
            if orig is None:
                os.environ.pop(
                    "SHOPAI_ENABLE_LIVE_EXECUTION", None,
                )
            else:
                os.environ[
                    "SHOPAI_ENABLE_LIVE_EXECUTION"
                ] = orig
        self.assertFalse(result.ok)
        self.assertEqual(
            len(recent_deliberations()), 0,
        )


class TestMcpSurface(unittest.TestCase):
    def setUp(self):
        reset_recent_for_tests()

    def tearDown(self):
        reset_recent_for_tests()

    def test_mcp_returns_publisher_record(self):
        bundle = _bundle()
        bundle.launch(_request())
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
            "launch", first["outcome"]["what"].lower(),
        )


if __name__ == "__main__":
    unittest.main()
