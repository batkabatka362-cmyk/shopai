"""Publisher failure → RCA auto-wire tests.

When publisher_bundle.launch() fails (ok=False, not dry_run),
the finalise path runs RCA and stashes the lesson on the
LaunchResult.note field. Owner sees it via
explain_decision + recent_decisions MCP.

Soft-fail discipline (§4b.E): an RCA exception must never
block the finalise path — the launch result still returns
with its original error, the lesson just won't be attached.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from execution.launch import publisher_bundle as pb

from tests.test_publisher_bundle import (  # type: ignore[import]
    _FakeAds, _FakeContent, _FakeOutcomes,
    _FakeProducts, _FakeRationale, _request,
)


def _bundle(**overrides):
    """Build a PublisherBundle with failing product creation
    so every launch ends ok=False."""
    kwargs = dict(
        content_generator=_FakeContent(),
        product_creator=_FakeProducts(status="error"),
        ad_adapter=_FakeAds(),
        outcome_recorder=_FakeOutcomes(),
        rationale_builder=_FakeRationale(),
    )
    kwargs.update(overrides)
    return pb.PublisherBundle(**kwargs)


class TestRCAWireOnFailure(unittest.TestCase):
    def setUp(self):
        # Ensure live execution IS on so the failure path
        # (ok=False, dry_run=False) triggers RCA.
        self._orig = os.environ.get(
            "SHOPAI_ENABLE_LIVE_EXECUTION",
        )
        os.environ["SHOPAI_ENABLE_LIVE_EXECUTION"] = "1"

    def tearDown(self):
        if self._orig is None:
            os.environ.pop(
                "SHOPAI_ENABLE_LIVE_EXECUTION", None,
            )
        else:
            os.environ[
                "SHOPAI_ENABLE_LIVE_EXECUTION"
            ] = self._orig

    def test_failed_launch_gets_lesson_note(self):
        """Non-dry-run failure path runs RCA and attaches
        lesson string to result.note."""
        bundle = _bundle()
        with patch(
            "core.learning.root_cause_analyzer."
            "RootCauseAnalyzer.analyze_failure",
            return_value={
                "root_causes": ["step error: forced"],
                "contributing_factors": [],
                "lesson": (
                    "When product creation fails, pause "
                    "launch and inspect payload"
                ),
                "prevention_rule": {},
            },
        ):
            result = bundle.launch(_request(live=True))
        self.assertFalse(result.ok)
        self.assertIn("lesson:", result.note)
        self.assertIn("product creation", result.note)

    def test_dry_run_failure_no_rca(self):
        """Dry-run failures don't trigger RCA — the launch
        was never live, so the failure doesn't constitute
        a production incident."""
        bundle = _bundle()
        call_count = {"n": 0}

        def counting_analyze(self, episode):
            call_count["n"] += 1
            return {"lesson": "should not fire"}

        with patch(
            "core.learning.root_cause_analyzer."
            "RootCauseAnalyzer.analyze_failure",
            counting_analyze,
        ):
            result = bundle.launch(_request(live=False))
        # launch is dry_run because live_execution gate is
        # on but request.live=False → dry_run=True
        self.assertTrue(result.dry_run)
        self.assertEqual(call_count["n"], 0)

    def test_rca_exception_does_not_block_finalise(self):
        """§4b.E soft-fail: RCA raising must not prevent the
        LaunchResult from being returned."""
        bundle = _bundle()
        with patch(
            "core.learning.root_cause_analyzer."
            "RootCauseAnalyzer.analyze_failure",
            side_effect=RuntimeError("rca broken"),
        ):
            result = bundle.launch(_request(live=True))
        # Launch still completed with ok=False + original
        # note, just without a lesson
        self.assertFalse(result.ok)
        self.assertNotIn("lesson:", result.note)
        # Original failure note preserved
        self.assertTrue(result.note)

    def test_empty_lesson_not_appended(self):
        """If RCA returns an empty lesson string, don't
        pollute the note with 'lesson: ' prefix."""
        bundle = _bundle()
        with patch(
            "core.learning.root_cause_analyzer."
            "RootCauseAnalyzer.analyze_failure",
            return_value={
                "root_causes": [],
                "contributing_factors": [],
                "lesson": "",
                "prevention_rule": {},
            },
        ):
            result = bundle.launch(_request(live=True))
        self.assertFalse(result.ok)
        self.assertNotIn("lesson:", result.note)

    def test_successful_launch_no_rca_invocation(self):
        """Happy-path launch must not run RCA — factor
        attribution on success is noise."""
        call_count = {"n": 0}

        def counting_analyze(self, episode):
            call_count["n"] += 1
            return {"lesson": "unwanted"}

        bundle = pb.PublisherBundle(
            content_generator=_FakeContent(),
            product_creator=_FakeProducts(status="created"),
            ad_adapter=_FakeAds(success=True),
            outcome_recorder=_FakeOutcomes(),
            rationale_builder=_FakeRationale(),
        )
        with patch(
            "core.learning.root_cause_analyzer."
            "RootCauseAnalyzer.analyze_failure",
            counting_analyze,
        ):
            result = bundle.launch(_request(live=True))
        self.assertTrue(result.ok)
        self.assertEqual(call_count["n"], 0)

    def test_lesson_truncated_to_240_chars(self):
        bundle = _bundle()
        long_lesson = "x" * 500
        with patch(
            "core.learning.root_cause_analyzer."
            "RootCauseAnalyzer.analyze_failure",
            return_value={
                "root_causes": [],
                "contributing_factors": [],
                "lesson": long_lesson,
                "prevention_rule": {},
            },
        ):
            result = bundle.launch(_request(live=True))
        # "lesson: " (8 chars) + up to 240 of the lesson +
        # the pre-existing "product creation failed" prefix
        # with " | "
        self.assertIn("lesson:", result.note)
        # The lesson portion shouldn't exceed 240 chars
        lesson_idx = result.note.find("lesson:")
        lesson_part = result.note[lesson_idx + 8:].strip()
        self.assertLessEqual(len(lesson_part), 240)


if __name__ == "__main__":
    unittest.main()
