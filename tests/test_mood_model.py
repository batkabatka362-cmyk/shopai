"""Mood model tests."""
from __future__ import annotations

import unittest

from core.brain import mood_model as mm


class TestConfig(unittest.TestCase):
    def test_bad_decay_raises(self) -> None:
        with self.assertRaises(ValueError):
            mm.MoodModel(decay_per_second=-0.1)


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        # No decay so tests are deterministic
        self.m = mm.MoodModel(decay_per_second=0.0)

    def test_bad_event_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.observe("weird")  # type: ignore[arg-type]

    def test_bad_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.observe("win", weight=-1)

    def test_win_raises_confidence(self) -> None:
        before = self.m.snapshot().confidence
        self.m.observe("win")
        self.assertGreater(
            self.m.snapshot().confidence, before,
        )

    def test_error_raises_stress(self) -> None:
        before = self.m.snapshot().stress
        self.m.observe("error")
        self.assertGreater(
            self.m.snapshot().stress, before,
        )

    def test_flat_no_change(self) -> None:
        c = self.m.snapshot().confidence
        s = self.m.snapshot().stress
        self.m.observe("flat")
        snap = self.m.snapshot()
        self.assertAlmostEqual(snap.confidence, c, places=4)
        self.assertAlmostEqual(snap.stress, s, places=4)

    def test_weight_scales_effect(self) -> None:
        m1 = mm.MoodModel(decay_per_second=0.0)
        m1.observe("win", weight=1.0)

        m2 = mm.MoodModel(decay_per_second=0.0)
        m2.observe("win", weight=2.0)

        self.assertGreater(
            m2.snapshot().confidence,
            m1.snapshot().confidence,
        )

    def test_clamped_0_1(self) -> None:
        for _ in range(50):
            self.m.observe("error", weight=2.0)
        self.assertLessEqual(self.m.snapshot().stress, 1.0)
        self.assertGreaterEqual(
            self.m.snapshot().confidence, 0.0,
        )


class TestDecay(unittest.TestCase):
    def test_decay_toward_baseline(self) -> None:
        m = mm.MoodModel(decay_per_second=1.0)
        # Push stress far up
        m.observe("overbudget", weight=3.0, ts=100.0)
        spiked = m.snapshot(now=100.0).stress
        # Wait "10 seconds"; decay fully pulls toward baseline
        relaxed = m.snapshot(now=110.0).stress
        self.assertLess(relaxed, spiked)


class TestLabel(unittest.TestCase):
    def test_labels(self) -> None:
        m = mm.MoodModel(decay_per_second=0.0)
        # Default = balanced
        self.assertIn(
            m.snapshot().label,
            {"balanced", "confident"},
        )
        # Push toward flow
        for _ in range(5):
            m.observe("praise")
            m.observe("win")
        self.assertIn(m.snapshot().label, {"flow", "confident"})

    def test_overwhelmed(self) -> None:
        m = mm.MoodModel(decay_per_second=0.0)
        for _ in range(5):
            m.observe("overbudget")
            m.observe("error")
            m.observe("criticise")
        self.assertIn(
            m.snapshot().label,
            {"overwhelmed", "stressed"},
        )


class TestTemperature(unittest.TestCase):
    def test_temperature_up_when_stressed(self) -> None:
        m = mm.MoodModel(decay_per_second=0.0)
        base = m.temperature()
        for _ in range(3):
            m.observe("error")
        self.assertGreater(m.temperature(), base)


class TestPredicates(unittest.TestCase):
    def test_is_confident(self) -> None:
        m = mm.MoodModel(decay_per_second=0.0)
        for _ in range(5):
            m.observe("win")
            m.observe("praise")
        self.assertTrue(m.is_confident())

    def test_is_stressed(self) -> None:
        m = mm.MoodModel(decay_per_second=0.0)
        for _ in range(3):
            m.observe("overbudget")
            m.observe("error")
        self.assertTrue(m.is_stressed())


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        m = mm.MoodModel()
        m.observe("win")
        s = m.stats()
        self.assertEqual(s["n_events"], 1)
        self.assertIn("label", s)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        m = mm.MoodModel()
        for _ in range(5):
            m.observe("error")
        self.assertEqual(m.reset(), 5)
        self.assertAlmostEqual(
            m.snapshot().stress, 0.2, places=2,
        )


class TestDict(unittest.TestCase):
    def test_snapshot_serialises(self) -> None:
        m = mm.MoodModel()
        d = m.snapshot().as_dict()
        self.assertIn("temperature", d)
        self.assertIn("label", d)


if __name__ == "__main__":
    unittest.main()
