"""Schedule optimizer tests."""
from __future__ import annotations

import datetime as dt
import unittest

from core.brain import schedule_optimizer as so


def _ts(weekday: int, hour: int) -> float:
    # Pick a known date: 2024-01-01 is a Monday (weekday=0)
    base = dt.datetime(2024, 1, 1 + weekday, hour)
    return base.timestamp()


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.o = so.ScheduleOptimizer()

    def test_record_and_histogram(self) -> None:
        self.o.record("alice", _ts(0, 8), 1.0)
        matrix = self.o.per_weekday_histogram("alice")
        self.assertEqual(len(matrix), 7)
        self.assertEqual(len(matrix[0]), 24)
        self.assertGreater(matrix[0][8], 0)

    def test_blank_entity_ignored(self) -> None:
        self.o.record("", _ts(0, 8), 1.0)
        self.assertEqual(self.o.stats()["entities"], 0)


class TestBestSlot(unittest.TestCase):
    def setUp(self) -> None:
        self.o = so.ScheduleOptimizer()

    def test_top_slot_is_highest_engagement(self) -> None:
        # Alice always reads at Monday 8am
        for _ in range(5):
            self.o.record("alice", _ts(0, 8), 1.0)
        # Few at Tuesday 10pm
        self.o.record("alice", _ts(1, 22), 0.1)
        best = self.o.best_slot("alice")
        self.assertEqual((best.weekday, best.hour), (0, 8))

    def test_top_k_returns_sorted(self) -> None:
        for _ in range(3):
            self.o.record("alice", _ts(0, 8), 1.0)
        for _ in range(3):
            self.o.record("alice", _ts(1, 10), 0.5)
        top = self.o.top_k_slots("alice", k=2)
        self.assertEqual(len(top), 2)
        self.assertGreater(top[0].score, top[1].score)

    def test_cold_entity_uses_global_fallback(self) -> None:
        self.o.record("bob", _ts(2, 14), 1.0)
        self.o.record("bob", _ts(2, 14), 1.0)
        best = self.o.best_slot("never_seen")
        # Falls back to global
        self.assertIsNotNone(best)
        self.assertEqual((best.weekday, best.hour), (2, 14))

    def test_truly_empty_returns_none(self) -> None:
        self.assertIsNone(self.o.best_slot("nobody"))


class TestGlobal(unittest.TestCase):
    def test_global_best_slot(self) -> None:
        o = so.ScheduleOptimizer()
        # Multiple entities all engage Wed 3pm
        for cust in range(5):
            o.record(f"c{cust}", _ts(2, 15), 1.0)
        best = o.global_best_slot()
        self.assertEqual((best.weekday, best.hour), (2, 15))


class TestSmoothing(unittest.TestCase):
    def test_single_record_non_zero_smoothed(self) -> None:
        o = so.ScheduleOptimizer()
        o.record("alice", _ts(0, 8), 0.0)
        matrix = o.per_weekday_histogram("alice")
        # Laplace smoothing → (0 + 1) / (1 + 2) = 0.333
        self.assertAlmostEqual(matrix[0][8], 1/3, places=2)


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        o = so.ScheduleOptimizer()
        o.record("a", _ts(0, 8), 1.0)
        o.record("a", _ts(0, 9), 0.5)
        o.record("b", _ts(1, 14), 1.0)
        stats = o.stats()
        self.assertEqual(stats["entities"], 2)
        self.assertEqual(stats["total_observations"], 3)


class TestSlot(unittest.TestCase):
    def test_slot_as_dict(self) -> None:
        s = so.Slot(weekday=3, hour=14, score=0.75, samples=10)
        d = s.as_dict()
        self.assertEqual(d["weekday"], 3)
        self.assertEqual(d["hour"], 14)
        self.assertAlmostEqual(d["score"], 0.75)


if __name__ == "__main__":
    unittest.main()
