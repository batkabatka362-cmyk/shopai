"""Action queue tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import action_queue as aq


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.q = aq.ActionQueue(Path(self._tmp.name) / "q.db")

    def tearDown(self) -> None:
        self.q.close()
        self._tmp.cleanup()


class TestEnqueue(TestSetup):
    def test_enqueue_returns_action(self) -> None:
        a = self.q.enqueue("kill_ad", payload={"ad_id": "a1"})
        self.assertEqual(a.kind, "kill_ad")
        self.assertEqual(a.status, "pending")

    def test_blank_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.q.enqueue("")

    def test_negative_retries_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.q.enqueue("kill", retries=-1)

    def test_explicit_id_used(self) -> None:
        a = self.q.enqueue("kill", action_id="custom_123")
        self.assertEqual(a.id, "custom_123")
        self.assertIsNotNone(self.q.get("custom_123"))


class TestNextDue(TestSetup):
    def test_only_due_returned(self) -> None:
        self.q.enqueue("now", priority=1)
        self.q.enqueue("later", delay_s=3600.0)
        due = self.q.next_due()
        kinds = [a.kind for a in due]
        self.assertIn("now", kinds)
        self.assertNotIn("later", kinds)

    def test_priority_orders_first(self) -> None:
        self.q.enqueue("low", priority=0)
        self.q.enqueue("high", priority=10)
        self.q.enqueue("medium", priority=5)
        due = self.q.next_due()
        self.assertEqual(
            [a.kind for a in due],
            ["high", "medium", "low"],
        )

    def test_dependency_blocks(self) -> None:
        a = self.q.enqueue("first")
        self.q.enqueue("second", depends_on=[a.id])
        due = self.q.next_due()
        kinds = [a.kind for a in due]
        self.assertIn("first", kinds)
        self.assertNotIn("second", kinds)

    def test_dependency_unblocks_when_done(self) -> None:
        a = self.q.enqueue("first")
        self.q.enqueue("second", depends_on=[a.id])
        self.q.mark_done(a.id)
        kinds = [x.kind for x in self.q.next_due()]
        self.assertIn("second", kinds)

    def test_limit_respected(self) -> None:
        for i in range(20):
            self.q.enqueue(f"k{i}")
        self.assertEqual(len(self.q.next_due(limit=5)), 5)


class TestStatusTransitions(TestSetup):
    def test_mark_running(self) -> None:
        a = self.q.enqueue("k")
        self.assertTrue(self.q.mark_running(a.id))
        self.assertEqual(self.q.get(a.id).status, "running")

    def test_mark_done(self) -> None:
        a = self.q.enqueue("k")
        self.q.mark_done(a.id)
        self.assertEqual(self.q.get(a.id).status, "done")

    def test_mark_failed_no_retries(self) -> None:
        a = self.q.enqueue("k")
        self.q.mark_failed(a.id, error="boom")
        self.assertEqual(self.q.get(a.id).status, "failed")
        self.assertEqual(self.q.get(a.id).last_error, "boom")

    def test_mark_failed_with_retries(self) -> None:
        a = self.q.enqueue("k", retries=2)
        self.q.mark_failed(a.id, "boom 1")
        # Should requeue, not fail
        self.assertEqual(self.q.get(a.id).status, "pending")
        self.assertEqual(self.q.get(a.id).retries, 1)
        self.q.mark_failed(a.id, "boom 2")
        self.assertEqual(self.q.get(a.id).status, "pending")
        self.assertEqual(self.q.get(a.id).retries, 0)
        self.q.mark_failed(a.id, "boom 3")
        # Out of retries → failed
        self.assertEqual(self.q.get(a.id).status, "failed")

    def test_cancel(self) -> None:
        a = self.q.enqueue("k")
        self.q.cancel(a.id)
        self.assertEqual(self.q.get(a.id).status, "cancelled")

    def test_unknown_action_returns_false(self) -> None:
        self.assertFalse(self.q.mark_done("nobody"))


class TestByStatus(TestSetup):
    def test_filter(self) -> None:
        self.q.enqueue("a")
        b = self.q.enqueue("b")
        self.q.mark_done(b.id)
        pend = self.q.by_status("pending")
        done = self.q.by_status("done")
        self.assertEqual(len(pend), 1)
        self.assertEqual(len(done), 1)


class TestPrune(TestSetup):
    def test_prune_old_terminal(self) -> None:
        a = self.q.enqueue("k")
        self.q.mark_done(a.id)
        # No prune yet — too recent
        self.assertEqual(self.q.prune_terminal(older_than_s=10), 0)
        # Force older_than_s = 0 to prune everything
        self.assertEqual(self.q.prune_terminal(older_than_s=0), 1)
        self.assertIsNone(self.q.get(a.id))

    def test_pending_not_pruned(self) -> None:
        self.q.enqueue("k")
        self.assertEqual(self.q.prune_terminal(older_than_s=0), 0)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "q.db"
        first = aq.ActionQueue(path)
        a = first.enqueue("k", payload={"x": 1})
        first.close()
        second = aq.ActionQueue(path)
        loaded = second.get(a.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.payload, {"x": 1})
        second.close()
        tmp.cleanup()


class TestStats(TestSetup):
    def test_stats_shape(self) -> None:
        self.q.enqueue("a")
        b = self.q.enqueue("b")
        self.q.mark_done(b.id)
        s = self.q.stats()
        self.assertEqual(s["pending"], 1)
        self.assertEqual(s["done"], 1)


class TestDict(TestSetup):
    def test_action_serialises(self) -> None:
        a = self.q.enqueue("k", payload={"x": 1}, priority=5)
        d = a.as_dict()
        self.assertEqual(d["kind"], "k")
        self.assertEqual(d["priority"], 5)
        self.assertEqual(d["payload"], {"x": 1})


if __name__ == "__main__":
    unittest.main()
