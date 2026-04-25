"""Intention tracker tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import intention_tracker as it


class TestDeclare(unittest.TestCase):
    def setUp(self) -> None:
        self.t = it.IntentionTracker()

    def test_blank_statement_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.declare(
                statement="",
                due_ts=time.time() + 100,
            )

    def test_past_due_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.declare(
                statement="x",
                due_ts=time.time() - 100,
            )

    def test_expected_needs_direction(self) -> None:
        with self.assertRaises(ValueError):
            self.t.declare(
                statement="x",
                due_ts=time.time() + 100,
                expected_value=10.0,
            )

    def test_happy_path(self) -> None:
        i = self.t.declare(
            statement="scale to $50",
            due_ts=time.time() + 86400,
            observable_kpi="daily_spend",
            expected_value=50.0,
            direction="above",
        )
        self.assertEqual(i.status, "pending")


class TestResolve(unittest.TestCase):
    def setUp(self) -> None:
        self.t = it.IntentionTracker()
        self.i = self.t.declare(
            statement="scale",
            due_ts=time.time() + 100,
            observable_kpi="spend",
            expected_value=50.0,
            direction="above",
        )

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.resolve("nope", observed_value=1.0)

    def test_fulfilled_above(self) -> None:
        r = self.t.resolve(
            self.i.id, observed_value=60.0,
        )
        self.assertEqual(r.status, "fulfilled")

    def test_expired_not_met(self) -> None:
        r = self.t.resolve(
            self.i.id, observed_value=10.0,
        )
        self.assertEqual(r.status, "expired")

    def test_past_due_ts_expires(self) -> None:
        r = self.t.resolve(
            self.i.id,
            observed_value=60.0,
            ts=time.time() + 9999,
        )
        self.assertEqual(r.status, "expired")

    def test_no_expected_fulfils(self) -> None:
        i = self.t.declare(
            statement="just do it",
            due_ts=time.time() + 100,
        )
        r = self.t.resolve(i.id, observed_value=0.0)
        self.assertEqual(r.status, "fulfilled")

    def test_cannot_double_resolve(self) -> None:
        self.t.resolve(self.i.id, observed_value=60)
        with self.assertRaises(ValueError):
            self.t.resolve(self.i.id, observed_value=60)

    def test_direction_below(self) -> None:
        i = self.t.declare(
            statement="cut cost",
            due_ts=time.time() + 100,
            expected_value=10.0, direction="below",
        )
        r = self.t.resolve(i.id, observed_value=5.0)
        self.assertEqual(r.status, "fulfilled")


class TestAbandon(unittest.TestCase):
    def test_abandon(self) -> None:
        t = it.IntentionTracker()
        i = t.declare(
            statement="x",
            due_ts=time.time() + 100,
        )
        r = t.abandon(i.id, note="owner canceled")
        self.assertEqual(r.status, "abandoned")
        self.assertEqual(r.note, "owner canceled")


class TestExpireOverdue(unittest.TestCase):
    def test_expire_overdue(self) -> None:
        t = it.IntentionTracker()
        i = t.declare(
            statement="x",
            due_ts=time.time() + 100,
        )
        n = t.expire_overdue(now=time.time() + 200)
        self.assertEqual(n, 1)
        self.assertEqual(t.get(i.id).status, "expired")


class TestQueries(unittest.TestCase):
    def test_pending(self) -> None:
        t = it.IntentionTracker()
        t.declare(
            statement="x",
            due_ts=time.time() + 100,
        )
        self.assertEqual(len(t.pending()), 1)

    def test_follow_through_rate(self) -> None:
        t = it.IntentionTracker()
        i1 = t.declare(
            statement="a",
            due_ts=time.time() + 100,
            expected_value=1, direction="above",
        )
        i2 = t.declare(
            statement="b",
            due_ts=time.time() + 100,
            expected_value=1, direction="above",
        )
        t.resolve(i1.id, observed_value=5)
        t.resolve(i2.id, observed_value=0)
        self.assertEqual(t.follow_through_rate(), 0.5)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "i.db"
        first = it.IntentionTracker(path)
        i = first.declare(
            statement="x",
            due_ts=time.time() + 1000,
        )
        first.resolve(i.id, observed_value=0.0)
        first.close()
        second = it.IntentionTracker(path)
        r = second.get(i.id)
        self.assertEqual(r.status, "fulfilled")
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        t = it.IntentionTracker()
        t.declare(
            statement="x",
            due_ts=time.time() + 100,
        )
        s = t.stats()
        self.assertEqual(s["total"], 1)
        self.assertIn("pending", s["by_status"])


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        t = it.IntentionTracker()
        i = t.declare(
            statement="x",
            due_ts=time.time() + 100,
        )
        d = i.as_dict()
        self.assertIn("statement", d)


if __name__ == "__main__":
    unittest.main()
