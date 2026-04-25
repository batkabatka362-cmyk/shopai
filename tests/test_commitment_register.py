"""Commitment register tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import commitment_register as cr


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = cr.CommitmentRegister(Path(self._tmp.name) / "c.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_returns_commitment(self) -> None:
        c = self.r.register(
            promise="reorder widgets",
            owner="brain",
            due_at=time.time() + 86_400,
        )
        self.assertEqual(c.status, "open")
        self.assertEqual(c.owner, "brain")

    def test_blank_promise_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.register("", "brain", due_at=time.time() + 60)

    def test_blank_owner_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.register("promise", "", due_at=time.time() + 60)

    def test_past_due_not_allowed(self) -> None:
        with self.assertRaises(ValueError):
            self.r.register("p", "o", due_at=0)


class TestTick(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = cr.CommitmentRegister(Path(self._tmp.name) / "c.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_fulfillment_test_resolves(self) -> None:
        c = self.r.register(
            promise="launch", owner="brain",
            due_at=time.time() + 3600,
            fulfillment_test=lambda: True,
        )
        self.r.tick()
        updated = self.r.get(c.id)
        self.assertEqual(updated.status, "fulfilled")

    def test_overdue_without_test_defaults(self) -> None:
        c = self.r.register(
            promise="x", owner="brain",
            due_at=time.time() - 1,  # already overdue
        )
        defaulted = self.r.tick()
        self.assertEqual(len(defaulted), 1)
        self.assertEqual(defaulted[0].id, c.id)
        self.assertEqual(self.r.get(c.id).status, "defaulted")

    def test_overdue_with_failing_test_defaults(self) -> None:
        c = self.r.register(
            promise="x", owner="brain",
            due_at=time.time() - 1,
            fulfillment_test=lambda: False,
        )
        self.r.tick()
        self.assertEqual(self.r.get(c.id).status, "defaulted")

    def test_broken_test_counts_as_unfulfilled(self) -> None:
        def boom():
            raise RuntimeError("bad")
        c = self.r.register(
            promise="x", owner="brain",
            due_at=time.time() + 10,
            fulfillment_test=boom,
        )
        # Still within deadline → stays open
        self.r.tick()
        self.assertEqual(self.r.get(c.id).status, "open")


class TestTransitions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = cr.CommitmentRegister(Path(self._tmp.name) / "c.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mark_fulfilled(self) -> None:
        c = self.r.register(
            "x", "brain", due_at=time.time() + 60,
        )
        self.assertTrue(self.r.mark_fulfilled(c.id, note="done"))
        updated = self.r.get(c.id)
        self.assertEqual(updated.status, "fulfilled")

    def test_cancel(self) -> None:
        c = self.r.register(
            "x", "brain", due_at=time.time() + 60,
        )
        self.assertTrue(self.r.cancel(c.id, reason="scope change"))
        self.assertEqual(self.r.get(c.id).status, "cancelled")

    def test_mark_twice_second_fails(self) -> None:
        c = self.r.register(
            "x", "brain", due_at=time.time() + 60,
        )
        self.r.mark_fulfilled(c.id)
        # Second attempt should not change state
        self.assertFalse(self.r.mark_fulfilled(c.id))


class TestListings(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.r = cr.CommitmentRegister(Path(self._tmp.name) / "c.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pending_ordered_by_due_soonest(self) -> None:
        now = time.time()
        a = self.r.register("a", "brain", due_at=now + 120)
        b = self.r.register("b", "brain", due_at=now + 60)
        pending = self.r.pending()
        self.assertEqual(pending[0].id, b.id)

    def test_urgent_filter(self) -> None:
        now = time.time()
        self.r.register("a", "brain", due_at=now + 3600 * 12)
        self.r.register("b", "brain", due_at=now + 3600 * 48)
        urgent = self.r.urgent(hours_ahead=24)
        self.assertEqual(len(urgent), 1)

    def test_pending_filter_by_owner(self) -> None:
        now = time.time()
        self.r.register("x", "alice", due_at=now + 60)
        self.r.register("y", "bob", due_at=now + 60)
        alice_only = self.r.pending(owner="alice")
        self.assertEqual(len(alice_only), 1)


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = cr.CommitmentRegister(Path(tmp.name) / "c.db")
        c1 = r.register("a", "b", due_at=time.time() + 60)
        c2 = r.register("a", "b", due_at=time.time() + 60)
        r.mark_fulfilled(c1.id)
        stats = r.stats()
        self.assertEqual(stats["counts"].get("fulfilled"), 1)
        self.assertEqual(stats["counts"].get("open"), 1)
        self.assertEqual(stats["total"], 2)
        tmp.cleanup()


class TestHoursUntilDue(unittest.TestCase):
    def test_hours_until_due(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        r = cr.CommitmentRegister(Path(tmp.name) / "c.db")
        future = time.time() + 7200
        c = r.register("x", "brain", due_at=future)
        h = c.hours_until_due()
        self.assertAlmostEqual(h, 2.0, delta=0.1)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
