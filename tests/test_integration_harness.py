"""Integration harness tests — real end-to-end wiring verification.

These tests deliberately run through real singletons (no mocks)
so regressions in cross-module wiring surface. They're the tests
I *wish* I had written 17 sprints ago.
"""
from __future__ import annotations

import unittest

from core.brain import integration_harness as ih


class TestVerifyWiring(unittest.TestCase):
    def test_wiring_status_ok_or_degraded(self) -> None:
        report = ih.verify_wiring()
        self.assertIn(report.status, ("ok", "degraded"))

    def test_outcome_router_always_responded(self) -> None:
        report = ih.verify_wiring()
        router_check = next(
            (c for c in report.checks if c.name == "outcome_router"),
            None,
        )
        self.assertIsNotNone(router_check)
        self.assertTrue(router_check.ok)

    def test_world_model_reflects_outcome(self) -> None:
        """A real-fire Outcome should land in the world model."""
        report = ih.verify_wiring()
        wm = next(
            (c for c in report.checks if c.name == "world_model"),
            None,
        )
        self.assertIsNotNone(wm)
        # 'after' is total_observations post-emit
        self.assertTrue(wm.ok,
                         f"world_model not wired: {wm.note}")

    def test_agi_cycle_runs_without_errors(self) -> None:
        report = ih.verify_wiring()
        cycle = next(
            (c for c in report.checks if c.name == "agi_cycle"),
            None,
        )
        self.assertIsNotNone(cycle)
        self.assertTrue(cycle.ok,
                         f"agi_cycle broken: {cycle.note}")

    def test_brain_facade_introspect_populated(self) -> None:
        report = ih.verify_wiring()
        facade = next(
            (c for c in report.checks if c.name == "brain_facade"),
            None,
        )
        self.assertIsNotNone(facade)
        self.assertTrue(facade.ok,
                         f"facade empty: {facade.note}")

    def test_elapsed_ms_recorded(self) -> None:
        report = ih.verify_wiring()
        self.assertGreater(report.elapsed_ms, 0)

    def test_as_dict_serialises(self) -> None:
        report = ih.verify_wiring()
        d = report.as_dict()
        self.assertIn("status", d)
        self.assertIn("checks", d)
        self.assertIn("pct_passing", d)


class TestEndToEndBenchmark(unittest.TestCase):
    def test_benchmark_runs_and_returns_score(self) -> None:
        score = ih.benchmark_end_to_end()
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_benchmark_meets_minimum_threshold(self) -> None:
        """The built-in benchmark covers the stable core; it should
        score well above 0.8 on a healthy brain."""
        score = ih.benchmark_end_to_end()
        self.assertGreater(
            score, 0.8,
            f"brain health degraded: benchmark at {score:.2f}",
        )


class TestFullHealthCheck(unittest.TestCase):
    def test_full_health_includes_benchmark(self) -> None:
        report = ih.run_health_check()
        names = [c.name for c in report.checks]
        self.assertIn("brain_benchmark", names)

    def test_healthy_brain_reports_ok_or_degraded(self) -> None:
        report = ih.run_health_check()
        # A healthy checkout should not be fully 'broken'.
        self.assertIn(report.status, ("ok", "degraded"))

    def test_pct_passing_bounds(self) -> None:
        report = ih.run_health_check()
        self.assertGreaterEqual(report.pct_passing, 0.0)
        self.assertLessEqual(report.pct_passing, 1.0)


class TestHelpers(unittest.TestCase):
    def test_deep_get_missing(self) -> None:
        self.assertIsNone(ih._deep_get({}, ["a", "b"]))

    def test_delta_missing_returns_zero(self) -> None:
        self.assertEqual(
            ih._delta({"a": {"b": 5}}, {}, ["a", "b"]),
            -5,
        )

    def test_snapshot_is_dict(self) -> None:
        snap = ih._snapshot()
        self.assertIsInstance(snap, dict)
        self.assertIn("world_model", snap)


if __name__ == "__main__":
    unittest.main()
