"""Working memory tests — push / salience / focus / housekeeping."""
from __future__ import annotations

import time
import unittest

from core.brain import working_memory as wm


class TestPushAndFocus(unittest.TestCase):
    def setUp(self) -> None:
        self.m = wm.WorkingMemory(capacity=3)

    def test_push_returns_incrementing_ids(self) -> None:
        a = self.m.push("order", {}, score=1)
        b = self.m.push("rule", {}, score=1)
        self.assertEqual(b, a + 1)

    def test_focus_capacity_limits_output(self) -> None:
        for i in range(6):
            self.m.push("note", {"i": i}, score=i)
        focus = self.m.focus()
        self.assertEqual(len(focus), 3)

    def test_owner_relevant_beats_generic(self) -> None:
        self.m.push("note", {"x": 1}, score=5.0)   # high score
        important_id = self.m.push(
            "owner_ping", {"msg": "reply asap"},
            urgency=3, owner_relevant=True,
        )
        focus = self.m.focus(capacity=1)
        self.assertEqual(focus[0].id, important_id)

    def test_focus_filter_by_kind(self) -> None:
        self.m.push("order", {}, score=1)
        self.m.push("rule", {}, score=1)
        self.m.push("order", {}, score=2)
        orders = self.m.focus(kinds=("order",))
        self.assertEqual({e.kind for e in orders}, {"order"})
        self.assertEqual(len(orders), 2)


class TestSalience(unittest.TestCase):
    def test_urgent_beats_old_high_score(self) -> None:
        m = wm.WorkingMemory(capacity=5)
        # Stale high-score event
        old_id = m.push("order", {}, score=5.0)
        # Backdate so recency decays
        for e in m._entries:
            if e.id == old_id:
                e.pushed_at = time.time() - 3600  # 1h ago
        # Fresh urgent event
        urgent_id = m.push("owner_ping", {"msg": "refund now"},
                           urgency=3, owner_relevant=True)
        focus = m.focus(capacity=1)
        self.assertEqual(focus[0].id, urgent_id)

    def test_urgency_clamps_to_0_3(self) -> None:
        m = wm.WorkingMemory()
        eid = m.push("x", {}, urgency=99)
        entry = next(e for e in m.all() if e.id == eid)
        self.assertEqual(entry.urgency, 3)

    def test_salience_score_between_0_and_1(self) -> None:
        m = wm.WorkingMemory()
        m.push("x", {}, urgency=3, score=5, owner_relevant=True)
        s = m.all()[0].salience()
        self.assertGreaterEqual(s, 0.0)
        self.assertLessEqual(s, 1.0)


class TestHousekeeping(unittest.TestCase):
    def test_reset_clears_all(self) -> None:
        m = wm.WorkingMemory()
        for _ in range(5):
            m.push("x", {})
        n = m.reset()
        self.assertEqual(n, 5)
        self.assertEqual(len(m), 0)

    def test_drop_older_than_evicts_ancient(self) -> None:
        m = wm.WorkingMemory()
        old_id = m.push("x", {})
        for e in m._entries:
            if e.id == old_id:
                e.pushed_at = time.time() - 1000
        recent = m.push("y", {})
        dropped = m.drop_older_than(500)
        self.assertEqual(dropped, 1)
        self.assertEqual(len(m), 1)
        self.assertEqual(m.all()[0].id, recent)


class TestSnapshot(unittest.TestCase):
    def test_snapshot_lists_focus_and_spill(self) -> None:
        m = wm.WorkingMemory(capacity=2)
        for i in range(5):
            m.push("note", {"i": i}, score=i)
        snap = m.snapshot()
        self.assertEqual(snap["capacity"], 2)
        self.assertEqual(snap["total"], 5)
        self.assertEqual(len(snap["in_focus_ids"]), 2)
        self.assertEqual(len(snap["spilled_ids"]), 3)


class TestSingleton(unittest.TestCase):
    def test_working_memory_returns_same_instance(self) -> None:
        m1 = wm.working_memory()
        m2 = wm.working_memory()
        self.assertIs(m1, m2)


if __name__ == "__main__":
    unittest.main()
