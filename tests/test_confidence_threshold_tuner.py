"""Confidence threshold tuner tests."""
from __future__ import annotations

import unittest

from core.brain import confidence_threshold_tuner as ctt


class TestConfig(unittest.TestCase):
    def test_bad_target_raises(self) -> None:
        with self.assertRaises(ValueError):
            ctt.ConfidenceThresholdTuner(target_win_rate=0)

    def test_bad_min_samples_raises(self) -> None:
        with self.assertRaises(ValueError):
            ctt.ConfidenceThresholdTuner(min_samples=2)

    def test_bad_fallback_raises(self) -> None:
        with self.assertRaises(ValueError):
            ctt.ConfidenceThresholdTuner(fallback_threshold=0)


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.t = ctt.ConfidenceThresholdTuner()

    def test_blank_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.record(
                kind="", confidence=0.5, outcome_ok=True,
            )

    def test_bad_confidence_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.record(
                kind="k", confidence=1.5, outcome_ok=True,
            )

    def test_record_stores(self) -> None:
        self.t.record(
            kind="price", confidence=0.7, outcome_ok=True,
        )
        self.assertEqual(
            self.t.stats()["total_samples"], 1,
        )


class TestThreshold(unittest.TestCase):
    def test_no_data_fallback(self) -> None:
        t = ctt.ConfidenceThresholdTuner(
            fallback_threshold=0.7,
        )
        self.assertEqual(t.threshold("unknown"), 0.7)

    def test_below_min_samples_fallback(self) -> None:
        t = ctt.ConfidenceThresholdTuner(
            min_samples=10, fallback_threshold=0.7,
        )
        for i in range(5):
            t.record(
                kind="k", confidence=0.9,
                outcome_ok=True,
            )
        self.assertEqual(t.threshold("k"), 0.7)

    def test_learns_lower_threshold_when_safe(self) -> None:
        # All confidences succeed → threshold can go low
        t = ctt.ConfidenceThresholdTuner(
            target_win_rate=0.8, min_samples=10,
        )
        for i in range(20):
            t.record(
                kind="k",
                confidence=0.3 + i * 0.01,
                outcome_ok=True,
            )
        tau = t.threshold("k")
        self.assertLess(tau, 0.7)

    def test_raises_threshold_when_low_conf_fails(self) -> None:
        # Low-conf fails at 0.5; high-conf wins at 0.9.
        # Tuner must push threshold above 0.5 to exclude losers.
        t = ctt.ConfidenceThresholdTuner(
            target_win_rate=0.8, min_samples=10,
        )
        for _ in range(20):
            t.record(
                kind="k", confidence=0.5,
                outcome_ok=False,
            )
            t.record(
                kind="k", confidence=0.9,
                outcome_ok=True,
            )
        tau = t.threshold("k")
        self.assertGreater(tau, 0.5)


class TestAccepts(unittest.TestCase):
    def test_accepts_above_threshold(self) -> None:
        t = ctt.ConfidenceThresholdTuner(
            fallback_threshold=0.6,
        )
        self.assertTrue(t.accepts("k", 0.8))
        self.assertFalse(t.accepts("k", 0.5))


class TestOverride(unittest.TestCase):
    def test_override_wins(self) -> None:
        t = ctt.ConfidenceThresholdTuner()
        for _ in range(20):
            t.record(
                kind="k", confidence=0.9,
                outcome_ok=True,
            )
        learned = t.threshold("k")
        t.set_override("k", 0.95)
        self.assertEqual(t.threshold("k"), 0.95)
        self.assertNotEqual(t.threshold("k"), learned)
        self.assertTrue(t.clear_override("k"))

    def test_bad_override_raises(self) -> None:
        t = ctt.ConfidenceThresholdTuner()
        with self.assertRaises(ValueError):
            t.set_override("k", 1.5)


class TestSummary(unittest.TestCase):
    def test_empty(self) -> None:
        t = ctt.ConfidenceThresholdTuner(
            fallback_threshold=0.7,
        )
        s = t.summary("k")
        self.assertEqual(s.n_samples, 0)
        self.assertEqual(s.recommended_threshold, 0.7)

    def test_with_samples(self) -> None:
        t = ctt.ConfidenceThresholdTuner(
            target_win_rate=0.8, min_samples=10,
        )
        for i in range(20):
            t.record(
                kind="k",
                confidence=0.5 + (i * 0.02),
                outcome_ok=(i >= 5),
            )
        s = t.summary("k")
        self.assertEqual(s.n_samples, 20)
        self.assertGreater(s.coverage_at_threshold, 0.0)

    def test_override_note(self) -> None:
        t = ctt.ConfidenceThresholdTuner()
        t.set_override("k", 0.9)
        s = t.summary("k")
        self.assertEqual(
            s.recommended_threshold, 0.9,
        )


class TestQueries(unittest.TestCase):
    def test_known_kinds(self) -> None:
        t = ctt.ConfidenceThresholdTuner()
        t.record(
            kind="a", confidence=0.5, outcome_ok=True,
        )
        t.record(
            kind="b", confidence=0.5, outcome_ok=True,
        )
        self.assertEqual(t.known_kinds(), ["a", "b"])

    def test_traces(self) -> None:
        t = ctt.ConfidenceThresholdTuner()
        t.record(
            kind="k", confidence=0.5, outcome_ok=True,
        )
        self.assertEqual(len(t.traces("k")), 1)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        t = ctt.ConfidenceThresholdTuner()
        t.record(
            kind="k", confidence=0.5, outcome_ok=True,
        )
        s = t.stats()
        self.assertEqual(s["total_samples"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        t = ctt.ConfidenceThresholdTuner()
        t.record(
            kind="k", confidence=0.5, outcome_ok=True,
        )
        self.assertEqual(t.reset(), 1)


class TestDict(unittest.TestCase):
    def test_sample_serialises(self) -> None:
        s = ctt.DecisionSample(
            kind="k", confidence=0.5,
            outcome_ok=True, ts=1.0,
        )
        d = s.as_dict()
        self.assertEqual(d["kind"], "k")

    def test_summary_serialises(self) -> None:
        t = ctt.ConfidenceThresholdTuner()
        d = t.summary("k").as_dict()
        self.assertIn("recommended_threshold", d)


if __name__ == "__main__":
    unittest.main()
