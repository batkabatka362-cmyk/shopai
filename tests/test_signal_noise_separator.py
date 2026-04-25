"""Signal/noise separator tests."""
from __future__ import annotations

import unittest

from core.brain import signal_noise_separator as sn


class TestConfig(unittest.TestCase):
    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            sn.SignalNoiseSeparator(window=2)

    def test_inverted_thresholds_raise(self) -> None:
        with self.assertRaises(ValueError):
            sn.SignalNoiseSeparator(
                drift_threshold=3.0,
                signal_threshold=2.0,
            )

    def test_bad_min_samples_raises(self) -> None:
        with self.assertRaises(ValueError):
            sn.SignalNoiseSeparator(min_samples=1)


class TestColdStart(unittest.TestCase):
    def test_cold_start_is_normal(self) -> None:
        s = sn.SignalNoiseSeparator(min_samples=5)
        v = s.observe("roas", 10.0)
        self.assertEqual(v.classification, "normal")
        self.assertIn("cold start", v.note)


class TestNormalRange(unittest.TestCase):
    def test_values_near_mean_normal(self) -> None:
        s = sn.SignalNoiseSeparator(min_samples=3)
        # Seed with a stable mean 10
        for v in (9.8, 10.2, 9.9, 10.1, 10.0):
            s.observe("roas", v)
        # A value very close → normal
        result = s.observe("roas", 10.05)
        self.assertEqual(result.classification, "normal")


class TestDriftAndSignal(unittest.TestCase):
    def test_drift_flagged(self) -> None:
        s = sn.SignalNoiseSeparator(
            min_samples=3, drift_threshold=1.0, signal_threshold=2.0,
        )
        # mean=10, stdev≈0.707 → new value 11.0 gives z≈1.41 → drift
        for v in (9.0, 10.0, 11.0, 10.0, 10.0):
            s.observe("x", v)
        result = s.observe("x", 11.0)
        self.assertEqual(result.classification, "drift")

    def test_signal_flagged(self) -> None:
        s = sn.SignalNoiseSeparator(
            min_samples=3, drift_threshold=1.0, signal_threshold=2.0,
        )
        for v in (9.9, 10.0, 10.1, 9.95, 10.05, 10.0):
            s.observe("x", v)
        result = s.observe("x", 15.0)
        self.assertEqual(result.classification, "signal")


class TestDirection(unittest.TestCase):
    def test_direction_up(self) -> None:
        s = sn.SignalNoiseSeparator(min_samples=2)
        s.observe("x", 5.0)
        s.observe("x", 5.0)
        r = s.observe("x", 10.0)
        self.assertEqual(r.direction, "up")

    def test_direction_down(self) -> None:
        s = sn.SignalNoiseSeparator(min_samples=2)
        s.observe("x", 10.0)
        s.observe("x", 10.0)
        r = s.observe("x", 5.0)
        self.assertEqual(r.direction, "down")

    def test_direction_flat(self) -> None:
        s = sn.SignalNoiseSeparator(min_samples=2)
        s.observe("x", 5.0)
        s.observe("x", 5.0)
        r = s.observe("x", 5.0)
        self.assertEqual(r.direction, "flat")


class TestWindow(unittest.TestCase):
    def test_window_eviction(self) -> None:
        s = sn.SignalNoiseSeparator(window=3, min_samples=2)
        # Fill window with low values; then shift mean high
        for v in (1.0, 1.0, 1.0, 10.0, 10.0, 10.0):
            s.observe("x", v)
        summary = s.summary("x")
        # Only last 3 survived; mean should be ~10
        self.assertAlmostEqual(summary["mean"], 10.0)
        self.assertEqual(summary["samples"], 3)


class TestObserveBatch(unittest.TestCase):
    def test_batch_returns_verdicts(self) -> None:
        s = sn.SignalNoiseSeparator(min_samples=2)
        # Slight variation so stdev > 0 before the outlier arrives
        verdicts = s.observe_batch(
            "x", [10.0, 10.1, 9.9, 10.0, 30.0],
        )
        self.assertEqual(len(verdicts), 5)
        # Last value is an outlier → drift or signal
        self.assertIn(
            verdicts[-1].classification, ("drift", "signal"),
        )


class TestSummary(unittest.TestCase):
    def test_summary_empty_none(self) -> None:
        s = sn.SignalNoiseSeparator()
        self.assertIsNone(s.summary("nope"))

    def test_summary_fields(self) -> None:
        s = sn.SignalNoiseSeparator(min_samples=2)
        for v in (1.0, 2.0, 3.0):
            s.observe("x", v)
        summary = s.summary("x")
        self.assertEqual(summary["samples"], 3)
        self.assertAlmostEqual(summary["mean"], 2.0)


class TestReset(unittest.TestCase):
    def test_reset_single(self) -> None:
        s = sn.SignalNoiseSeparator()
        s.observe("a", 1.0)
        s.observe("b", 1.0)
        self.assertEqual(s.reset("a"), 1)
        self.assertIsNone(s.summary("a"))
        self.assertIsNotNone(s.summary("b"))

    def test_reset_all(self) -> None:
        s = sn.SignalNoiseSeparator()
        s.observe("a", 1.0)
        s.observe("b", 1.0)
        self.assertEqual(s.reset(), 2)


class TestBlankMetric(unittest.TestCase):
    def test_blank_raises(self) -> None:
        s = sn.SignalNoiseSeparator()
        with self.assertRaises(ValueError):
            s.observe("", 1.0)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        s = sn.SignalNoiseSeparator()
        s.observe("a", 1.0)
        st = s.stats()
        self.assertEqual(st["metrics_tracked"], 1)
        self.assertIn("window", st)


class TestDict(unittest.TestCase):
    def test_verdict_serialises(self) -> None:
        s = sn.SignalNoiseSeparator()
        v = s.observe("x", 1.0)
        d = v.as_dict()
        self.assertIn("classification", d)
        self.assertIn("direction", d)


if __name__ == "__main__":
    unittest.main()
