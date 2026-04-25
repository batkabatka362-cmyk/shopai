"""Goal graph tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import goal_graph as gg


class TestAdd(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.g = gg.GoalGraph(Path(self._tmp.name) / "g.db")

    def tearDown(self) -> None:
        self.g.close()
        self._tmp.cleanup()

    def test_add_root(self) -> None:
        g = self.g.add("ship v23")
        self.assertEqual(g.description, "ship v23")
        self.assertEqual(g.progress, 0.0)
        self.assertEqual(g.status, "open")

    def test_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.g.add("")

    def test_bad_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.g.add("x", weight=0)

    def test_unknown_parent_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.g.add("child", parent_id="nobody")

    def test_child_inherits_parent_link(self) -> None:
        p = self.g.add("parent")
        c = self.g.add("child", parent_id=p.id)
        self.assertEqual(c.parent_id, p.id)
        kids = self.g.children(p.id)
        self.assertEqual(len(kids), 1)


class TestProgress(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.g = gg.GoalGraph(Path(self._tmp.name) / "g.db")

    def tearDown(self) -> None:
        self.g.close()
        self._tmp.cleanup()

    def test_advance_updates_leaf(self) -> None:
        g = self.g.add("x")
        self.g.advance(g.id, 0.5)
        self.assertAlmostEqual(self.g.get(g.id).progress, 0.5)

    def test_advance_clamps(self) -> None:
        g = self.g.add("x")
        self.g.advance(g.id, 1.5)
        self.assertAlmostEqual(self.g.get(g.id).progress, 1.0)

    def test_full_progress_marks_met(self) -> None:
        g = self.g.add("x")
        self.g.advance(g.id, 1.0)
        self.assertEqual(self.g.get(g.id).status, "met")

    def test_rollup_weighted(self) -> None:
        p = self.g.add("p")
        c1 = self.g.add("c1", parent_id=p.id, weight=1.0)
        c2 = self.g.add("c2", parent_id=p.id, weight=3.0)
        self.g.advance(c1.id, 1.0)
        self.g.advance(c2.id, 0.0)
        # weighted: (1.0×1 + 0.0×3) / 4 = 0.25
        self.assertAlmostEqual(self.g.get(p.id).progress, 0.25)

    def test_all_children_met_marks_parent_met(self) -> None:
        p = self.g.add("p")
        c1 = self.g.add("c1", parent_id=p.id)
        c2 = self.g.add("c2", parent_id=p.id)
        self.g.advance(c1.id, 1.0)
        self.g.advance(c2.id, 1.0)
        self.assertEqual(self.g.get(p.id).status, "met")

    def test_child_blocked_propagates_to_parent(self) -> None:
        p = self.g.add("p")
        c = self.g.add("c", parent_id=p.id)
        self.g.mark_status(c.id, "blocked")
        self.assertEqual(self.g.get(p.id).status, "blocked")

    def test_deep_rollup_transitive(self) -> None:
        gp = self.g.add("gp")
        p = self.g.add("p", parent_id=gp.id)
        c = self.g.add("c", parent_id=p.id)
        self.g.advance(c.id, 1.0)
        self.assertEqual(self.g.get(gp.id).status, "met")


class TestFrontier(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.g = gg.GoalGraph(Path(self._tmp.name) / "g.db")

    def tearDown(self) -> None:
        self.g.close()
        self._tmp.cleanup()

    def test_leaf_open_is_in_frontier(self) -> None:
        p = self.g.add("parent")
        c = self.g.add("child", parent_id=p.id)
        front = self.g.frontier()
        ids = [g.id for g in front]
        self.assertIn(c.id, ids)
        self.assertNotIn(p.id, ids)

    def test_met_child_excluded(self) -> None:
        p = self.g.add("parent")
        c = self.g.add("child", parent_id=p.id)
        self.g.advance(c.id, 1.0)
        self.assertEqual(self.g.frontier(), [])

    def test_solo_open_root_is_frontier(self) -> None:
        r = self.g.add("alone")
        front = self.g.frontier()
        self.assertEqual(len(front), 1)
        self.assertEqual(front[0].id, r.id)


class TestOverdue(unittest.TestCase):
    def test_overdue_flagged(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        g = gg.GoalGraph(Path(tmp.name) / "g.db")
        g.add("late", due_at=time.time() - 100)
        g.add("future", due_at=time.time() + 10_000)
        g.add("none")
        od = g.overdue()
        self.assertEqual(len(od), 1)
        self.assertEqual(od[0].description, "late")
        g.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        g = gg.GoalGraph(Path(tmp.name) / "g.db")
        g.add("a")
        b = g.add("b")
        g.mark_status(b.id, "blocked")
        s = g.stats()
        self.assertGreaterEqual(s["open"], 1)
        self.assertGreaterEqual(s["blocked"], 1)
        g.close()
        tmp.cleanup()


class TestDict(unittest.TestCase):
    def test_goal_serialises(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        g = gg.GoalGraph(Path(tmp.name) / "g.db")
        goal = g.add("x", tags=("a", "b"))
        d = goal.as_dict()
        self.assertEqual(d["description"], "x")
        self.assertEqual(d["tags"], ["a", "b"])
        g.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
