"""Tests for the audit batch 3 wire-up: FeedbackStore +
ImprovementTracker were previously orphan modules (0 callers
outside tests). This batch connects them:

  * EngineOutcomeBus now has a feedback_store sink — every
    activator / publisher outcome lands in
    ``feedback_store.get_all_stats()``.
  * MCP tools ``engine_feedback_stats`` +
    ``improvements_summary`` expose the learning ledger to
    the owner via Claude Desktop.

§4d principle: "silent delete огт үгүй. сул хэсэг → reconnect,
не remove." These tests lock the reconnection so the modules
never drift back to orphan status.
"""
from __future__ import annotations

import tempfile
import unittest

from core.integration.engine_outcome_bus import (
    EngineOutcome,
    EngineOutcomeBus,
)
from core.learning.feedback_store import FeedbackStore


class _InertSink:
    """Placeholder for sinks we don't want to exercise in
    wire-up tests — forces the bus to use only the one under
    test."""

    def touch(self, *a, **kw):
        return None

    def record_outcome(self, *a, **kw):
        return None

    def mine(self, *a, **kw):
        return type("R", (), {"proposals_emitted": 0})()

    def predict(self, *a, **kw):
        return None


class TestBusToFeedbackStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fb_wire_")
        self.fb = FeedbackStore(store_dir=self.tmp)
        # Isolate — feed the bus a real FeedbackStore and
        # inert everything else so only one sink fires.
        self.bus = EngineOutcomeBus(
            feedback_store=self.fb,
            freshness_tracker=_InertSink(),
            trust_calibrator=_InertSink(),
            world_calibration=_InertSink(),
            pattern_miner=_InertSink(),
            mine_every=1000,
            pattern_window=1000,
        )

    def test_report_creates_feedback_entry(self):
        report = self.bus.report(EngineOutcome(
            engine="campaign_activator",
            kpi="activation", value=1.0, ok=True,
            source="meta_ads",
            context={"niche": "pet"},
        ))
        self.assertIn("feedback_store", report.sinks_invoked)
        hist = self.fb.get_history("campaign_activator")
        self.assertEqual(len(hist), 1)
        entry = hist[0]
        self.assertEqual(entry["status"], "completed")
        self.assertEqual(entry["engine_name"], "campaign_activator")

    def test_failed_outcome_marks_failed(self):
        self.bus.report(EngineOutcome(
            engine="publisher_bundle",
            kpi="launched", value=0.0, ok=False,
        ))
        hist = self.fb.get_history("publisher_bundle")
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["status"], "failed")

    def test_quality_score_captured_when_numeric(self):
        self.bus.report(EngineOutcome(
            engine="pricing_engine",
            kpi="margin", value=0.22, ok=True,
        ))
        hist = self.fb.get_history("pricing_engine")
        self.assertEqual(hist[0]["quality_score"], 0.22)

    def test_feedback_store_failure_does_not_block_report(self):
        """§4b.E failure isolation: a broken feedback sink
        must never prevent the bus from returning a report."""

        class _BrokenFB:
            def record(self, **kwargs):
                raise RuntimeError("disk full")

        bus = EngineOutcomeBus(
            feedback_store=_BrokenFB(),
            freshness_tracker=_InertSink(),
            trust_calibrator=_InertSink(),
            world_calibration=_InertSink(),
            pattern_miner=_InertSink(),
            mine_every=1000,
            pattern_window=1000,
        )
        report = bus.report(EngineOutcome(
            engine="x", kpi="k", value=1.0, ok=True,
        ))
        self.assertIn(
            "feedback_store", report.sink_errors,
        )
        self.assertIn(
            "disk full",
            report.sink_errors["feedback_store"],
        )

    def test_aggregated_stats(self):
        for i in range(5):
            self.bus.report(EngineOutcome(
                engine="eng1", kpi="k", value=1.0, ok=True,
            ))
        for i in range(2):
            self.bus.report(EngineOutcome(
                engine="eng1", kpi="k", value=0.0, ok=False,
            ))
        stats = self.fb.get_stats("eng1")
        self.assertEqual(stats["total_runs"], 7)
        self.assertEqual(stats["completed"], 5)
        self.assertEqual(stats["failed"], 2)
        self.assertAlmostEqual(
            stats["success_rate"], 5 / 7, places=3,
        )


class TestFeedbackStoreSingleton(unittest.TestCase):
    def test_singleton_returns_same_instance(self):
        from core.learning.feedback_store import (
            get_feedback_store,
            reset_feedback_store_for_tests,
        )
        reset_feedback_store_for_tests()
        a = get_feedback_store()
        b = get_feedback_store()
        self.assertIs(a, b)
        reset_feedback_store_for_tests()


class TestMCPFeedbackTools(unittest.TestCase):
    def test_engine_feedback_stats_registered(self):
        from mcp_server.tools import build_default_registry

        reg = build_default_registry()
        specs = {s.name: s for s in reg.list_tools()}
        self.assertIn("engine_feedback_stats", specs)
        self.assertFalse(specs["engine_feedback_stats"].write)
        self.assertIn("improvements_summary", specs)
        self.assertFalse(specs["improvements_summary"].write)

    def test_engine_feedback_stats_handler_returns_shape(self):
        from mcp_server.tools import (
            _engine_feedback_stats_handler,
        )
        out = _engine_feedback_stats_handler({})
        self.assertIn("engines", out)
        self.assertIn("persist_errors", out)

    def test_engine_feedback_stats_single_engine(self):
        from core.learning.feedback_store import (
            get_feedback_store, reset_feedback_store_for_tests,
        )
        import tempfile

        d = tempfile.mkdtemp(prefix="fb_mcp_")
        reset_feedback_store_for_tests(store_dir=d)
        try:
            fb = get_feedback_store()
            fb.record(
                engine_name="my_engine",
                task_id="t1",
                status="completed",
                elapsed_seconds=0.1,
            )
            from mcp_server.tools import (
                _engine_feedback_stats_handler,
            )
            out = _engine_feedback_stats_handler({
                "engine": "my_engine",
            })
            self.assertEqual(out["engine"], "my_engine")
            self.assertEqual(out["total_runs"], 1)
        finally:
            reset_feedback_store_for_tests()

    def test_improvements_summary_handler_shape(self):
        from mcp_server.tools import (
            _improvements_summary_handler,
        )
        out = _improvements_summary_handler({"limit": 5})
        for k in (
            "total", "proposed", "applied", "measured",
            "by_type", "proposed_samples", "applied_samples",
        ):
            self.assertIn(k, out)
        self.assertLessEqual(len(out["proposed_samples"]), 5)


if __name__ == "__main__":
    unittest.main()
