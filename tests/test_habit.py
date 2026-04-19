"""Habit formation tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import habit as hb


class TestSignature(unittest.TestCase):
    def test_signature_is_stable_across_key_order(self) -> None:
        a = hb.signature_for({"niche": "audio", "tone": "luxury"})
        b = hb.signature_for({"tone": "luxury", "niche": "audio"})
        self.assertEqual(a, b)

    def test_signature_lowercases(self) -> None:
        s = hb.signature_for({"niche": "AUDIO"})
        self.assertIn("audio", s)

    def test_signature_drops_none(self) -> None:
        s = hb.signature_for({"a": 1, "b": None})
        self.assertIn("a=1", s)
        self.assertNotIn("b=", s)


class TestPromotion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.h = hb.HabitLayer(
            Path(self._tmp.name) / "h.db",
            min_fires=3, min_win_rate=0.75,
            failure_window_s=86_400,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_promotes_after_enough_wins(self) -> None:
        sig = "niche=audio|tone=friendly"
        for _ in range(3):
            result = self.h.observe(sig, "scale", success=True)
        # Third observation should promote (fires=3, wins=3, rate=1)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "active")

    def test_no_promotion_below_threshold(self) -> None:
        sig = "x"
        self.h.observe(sig, "scale", success=True)
        self.h.observe(sig, "scale", success=True)
        # Only 2 fires, threshold=3
        self.assertIsNone(self.h.reflex(sig))

    def test_low_win_rate_no_promotion(self) -> None:
        sig = "y"
        for _ in range(3):
            self.h.observe(sig, "scale", success=True)
            self.h.observe(sig, "scale", success=False)
        # 6 fires, 3 wins = 0.5 rate
        self.assertIsNone(self.h.reflex(sig))


class TestBreak(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.h = hb.HabitLayer(
            Path(self._tmp.name) / "h.db",
            min_fires=3, min_win_rate=0.75,
            failure_window_s=86_400,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_failure_after_promotion_breaks(self) -> None:
        sig = "z"
        for _ in range(3):
            self.h.observe(sig, "scale", success=True)
        self.assertIsNotNone(self.h.reflex(sig))
        self.h.observe(sig, "scale", success=False)
        self.assertIsNone(self.h.reflex(sig))

    def test_manual_break(self) -> None:
        sig = "k"
        for _ in range(3):
            self.h.observe(sig, "scale", success=True)
        habit = self.h.reflex(sig)
        self.assertTrue(self.h.break_habit(habit.id, note="overrule"))
        self.assertIsNone(self.h.reflex(sig))


class TestReflex(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.h = hb.HabitLayer(
            Path(self._tmp.name) / "h.db",
            min_fires=3, min_win_rate=0.75,
            failure_window_s=86_400,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reflex_returns_habit(self) -> None:
        sig = "audio"
        for _ in range(3):
            self.h.observe(sig, "scale", success=True)
        habit = self.h.reflex(sig)
        self.assertIsNotNone(habit)
        self.assertEqual(habit.action, "scale")

    def test_reflex_unknown_returns_none(self) -> None:
        self.assertIsNone(self.h.reflex("never_seen"))


class TestRecentFailureBlocks(unittest.TestCase):
    def test_recent_failure_blocks_promotion(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        h = hb.HabitLayer(
            Path(tmp.name) / "h.db",
            min_fires=3, min_win_rate=0.5,    # lowered so failure+wins pass rate
            failure_window_s=86_400,
        )
        sig = "s"
        now = time.time()
        h.observe(sig, "scale", success=False, now=now - 100)
        for i in range(3):
            h.observe(sig, "scale", success=True, now=now)
        # fires=4, wins=3, rate=0.75, but last_failure within 24h
        self.assertIsNone(h.reflex(sig))
        tmp.cleanup()


class TestListings(unittest.TestCase):
    def test_active_and_broken_listings(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        h = hb.HabitLayer(
            Path(tmp.name) / "h.db",
            min_fires=3, min_win_rate=0.75,
        )
        for _ in range(3):
            h.observe("active_sig", "scale", success=True)
        for _ in range(3):
            h.observe("bad_sig", "scale", success=True)
        broken = h.reflex("bad_sig")
        h.break_habit(broken.id, note="test")
        self.assertEqual(len(h.active_habits()), 1)
        self.assertEqual(len(h.broken_habits()), 1)
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        h = hb.HabitLayer(
            Path(tmp.name) / "h.db",
            min_fires=3, min_win_rate=0.75,
        )
        for _ in range(3):
            h.observe("a", "x", success=True)
        h.observe("b", "y", success=False)
        stats = h.stats()
        self.assertEqual(stats["signatures"], 2)
        self.assertEqual(stats["total_wins"], 3)
        self.assertEqual(stats["habits"].get("active"), 1)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
