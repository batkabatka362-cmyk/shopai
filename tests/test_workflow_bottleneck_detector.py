"""Workflow bottleneck detector tests."""
from __future__ import annotations

import unittest

from core.brain import workflow_bottleneck_detector as wbd


class TestConfig(unittest.TestCase):
    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            wbd.WorkflowBottleneckDetector(window=5)

    def test_bad_slow_factor_raises(self) -> None:
        with self.assertRaises(ValueError):
            wbd.WorkflowBottleneckDetector(slow_factor=1.0)

    def test_bad_error_floor_raises(self) -> None:
        with self.assertRaises(ValueError):
            wbd.WorkflowBottleneckDetector(
                error_rate_floor=0,
            )


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.d = wbd.WorkflowBottleneckDetector()

    def test_blank_phase_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.d.record(
                phase="", duration_ms=1.0, ok=True,
            )

    def test_negative_duration_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.d.record(
                phase="p", duration_ms=-1.0, ok=True,
            )

    def test_record_stored(self) -> None:
        self.d.record(
            phase="p", duration_ms=10.0, ok=True,
        )
        self.assertEqual(self.d.stats()["total_samples"], 1)


class TestStats(unittest.TestCase):
    def test_all_stats_empty(self) -> None:
        d = wbd.WorkflowBottleneckDetector()
        self.assertEqual(d.all_stats(), [])

    def test_per_phase_stats(self) -> None:
        d = wbd.WorkflowBottleneckDetector()
        for i in range(10):
            d.record(
                phase="fast",
                duration_ms=10.0, ok=True,
            )
            d.record(
                phase="slow",
                duration_ms=100.0, ok=True,
            )
        stats = d.all_stats()
        self.assertEqual(stats[0].phase, "slow")
        self.assertEqual(stats[0].mean_ms, 100.0)


class TestBottleneck(unittest.TestCase):
    def test_latency_bottleneck(self) -> None:
        d = wbd.WorkflowBottleneckDetector(
            slow_factor=2.0, error_rate_floor=0.5,
        )
        for _ in range(10):
            d.record(
                phase="a", duration_ms=10.0, ok=True,
            )
            d.record(
                phase="b", duration_ms=10.0, ok=True,
            )
        for _ in range(10):
            d.record(
                phase="slow", duration_ms=1000.0, ok=True,
            )
        b = d.top_bottleneck()
        self.assertEqual(b.phase, "slow")
        self.assertEqual(b.reason, "latency")

    def test_error_bottleneck_wins_over_latency(self) -> None:
        d = wbd.WorkflowBottleneckDetector(
            slow_factor=2.0, error_rate_floor=0.1,
        )
        for _ in range(10):
            d.record(
                phase="a", duration_ms=10.0, ok=True,
            )
            d.record(
                phase="slow", duration_ms=1000.0, ok=True,
            )
            d.record(
                phase="flaky",
                duration_ms=10.0, ok=False,
            )
        b = d.top_bottleneck()
        self.assertEqual(b.phase, "flaky")
        self.assertEqual(b.reason, "errors")

    def test_no_bottleneck_returns_none(self) -> None:
        d = wbd.WorkflowBottleneckDetector(
            slow_factor=3.0, error_rate_floor=0.5,
        )
        for _ in range(10):
            d.record(
                phase="a", duration_ms=10.0, ok=True,
            )
            d.record(
                phase="b", duration_ms=12.0, ok=True,
            )
        self.assertIsNone(d.top_bottleneck())

    def test_all_bottlenecks_multiple(self) -> None:
        d = wbd.WorkflowBottleneckDetector(
            slow_factor=2.0, error_rate_floor=0.1,
        )
        for _ in range(10):
            d.record(
                phase="a", duration_ms=10.0, ok=True,
            )
            d.record(
                phase="slow", duration_ms=1000.0, ok=True,
            )
            d.record(
                phase="flaky",
                duration_ms=10.0, ok=False,
            )
        b_list = d.all_bottlenecks()
        phases = {b.phase for b in b_list}
        self.assertIn("slow", phases)
        self.assertIn("flaky", phases)


class TestWindow(unittest.TestCase):
    def test_window_bounded(self) -> None:
        d = wbd.WorkflowBottleneckDetector(window=10)
        for i in range(20):
            d.record(
                phase="p", duration_ms=float(i), ok=True,
            )
        stats = d.all_stats()
        self.assertEqual(stats[0].n, 10)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        d = wbd.WorkflowBottleneckDetector()
        d.record(
            phase="p", duration_ms=10.0, ok=True,
        )
        self.assertEqual(d.reset(), 1)


class TestDict(unittest.TestCase):
    def test_sample_serialises(self) -> None:
        s = wbd.PhaseSample(
            phase="p", duration_ms=1.0,
            ok=True, ts=0.0,
        )
        d = s.as_dict()
        self.assertEqual(d["phase"], "p")

    def test_stat_serialises(self) -> None:
        d = wbd.WorkflowBottleneckDetector()
        d.record(
            phase="p", duration_ms=10.0, ok=True,
        )
        s = d.all_stats()[0]
        self.assertIn("mean_ms", s.as_dict())

    def test_bottleneck_serialises(self) -> None:
        d = wbd.WorkflowBottleneckDetector(
            slow_factor=2.0, error_rate_floor=0.5,
        )
        for _ in range(10):
            d.record(
                phase="fast", duration_ms=1.0, ok=True,
            )
            d.record(
                phase="slow", duration_ms=1000.0, ok=True,
            )
        b = d.top_bottleneck()
        if b:
            self.assertIn("stat", b.as_dict())


if __name__ == "__main__":
    unittest.main()
