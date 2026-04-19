"""Curiosity engine tests."""
from __future__ import annotations

import time
import unittest

from core.brain import curiosity_engine as ce


class TestNote(unittest.TestCase):
    def test_high_error_accepted(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        item = e.note("obs1", predicted=0.2, actual=0.9)
        self.assertIsNotNone(item)
        self.assertAlmostEqual(item.error, 0.7)

    def test_low_error_rejected(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        self.assertIsNone(e.note("obs1", predicted=0.5, actual=0.55))

    def test_blank_id_raises(self) -> None:
        e = ce.CuriosityEngine()
        with self.assertRaises(ValueError):
            e.note("", predicted=0.0, actual=1.0)

    def test_invalid_config_raises(self) -> None:
        with self.assertRaises(ValueError):
            ce.CuriosityEngine(min_error=-0.1)
        with self.assertRaises(ValueError):
            ce.CuriosityEngine(half_life_s=0)


class TestDedup(unittest.TestCase):
    def test_same_context_higher_error_wins(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        ctx = {"niche": "audio"}
        e.note("o1", predicted=0.5, actual=0.8, context=ctx)
        e.note("o2", predicted=0.5, actual=0.95, context=ctx)
        self.assertEqual(e.pending(), 1)
        remaining = e.peek(5)[0]
        self.assertEqual(remaining.id, "o2")

    def test_same_context_lower_error_skipped(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        ctx = {"niche": "audio"}
        e.note("o1", predicted=0.5, actual=0.95, context=ctx)
        # Smaller error — should not displace
        res = e.note("o2", predicted=0.5, actual=0.7, context=ctx)
        self.assertIsNone(res)
        self.assertEqual(e.pending(), 1)

    def test_different_contexts_both_kept(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        e.note("a", predicted=0.2, actual=0.9, context={"niche": "a"})
        e.note("b", predicted=0.2, actual=0.9, context={"niche": "b"})
        self.assertEqual(e.pending(), 2)


class TestNextProbe(unittest.TestCase):
    def test_highest_error_first(self) -> None:
        e = ce.CuriosityEngine(min_error=0.05)
        e.note("small", predicted=0.5, actual=0.6,
                context={"x": 1})
        e.note("huge",  predicted=0.0, actual=0.9,
                context={"x": 2})
        e.note("mid",   predicted=0.3, actual=0.7,
                context={"x": 3})
        probe = e.next_probe()
        self.assertEqual(probe.id, "huge")

    def test_next_probe_consumes(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        e.note("o1", predicted=0.2, actual=0.9)
        first = e.next_probe()
        self.assertEqual(first.id, "o1")
        self.assertIsNone(e.next_probe())

    def test_empty_returns_none(self) -> None:
        e = ce.CuriosityEngine()
        self.assertIsNone(e.next_probe())


class TestPeek(unittest.TestCase):
    def test_peek_does_not_consume(self) -> None:
        e = ce.CuriosityEngine(min_error=0.05)
        e.note("o1", predicted=0.2, actual=0.9, context={"x": 1})
        e.note("o2", predicted=0.3, actual=0.95, context={"x": 2})
        peek1 = e.peek(5)
        peek2 = e.peek(5)
        self.assertEqual(len(peek1), 2)
        self.assertEqual(len(peek2), 2)


class TestResolve(unittest.TestCase):
    def test_resolve_marks_done(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        e.note("o1", predicted=0.2, actual=0.9)
        self.assertEqual(e.pending(), 1)
        self.assertTrue(e.resolve("o1"))
        self.assertEqual(e.pending(), 0)

    def test_resolve_unknown_false(self) -> None:
        e = ce.CuriosityEngine()
        self.assertFalse(e.resolve("nobody"))


class TestRecency(unittest.TestCase):
    def test_fresh_beats_stale_at_equal_error(self) -> None:
        e = ce.CuriosityEngine(min_error=0.05, half_life_s=1.0)
        # Inject an older item
        old = e.note("old", predicted=0.2, actual=0.9, context={"x": 1})
        old.ts = time.time() - 5  # 5× half-life ago
        e._items[old.id] = old
        e.note("new", predicted=0.2, actual=0.9, context={"x": 2})
        probe = e.next_probe()
        self.assertEqual(probe.id, "new")


class TestCap(unittest.TestCase):
    def test_max_items_enforced(self) -> None:
        e = ce.CuriosityEngine(min_error=0.05, max_items=3)
        for i in range(10):
            e.note(f"o{i}", predicted=0.2, actual=0.9 - i * 0.01,
                    context={"x": i})
        self.assertLessEqual(e.pending(), 3)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        e.note("o1", predicted=0.2, actual=0.9)
        s = e.stats()
        self.assertIn("pending", s)
        self.assertIn("resolved", s)
        self.assertIn("max_error", s)
        self.assertEqual(s["pending"], 1)
        self.assertAlmostEqual(s["max_error"], 0.7, places=3)


class TestDict(unittest.TestCase):
    def test_item_serialises(self) -> None:
        e = ce.CuriosityEngine(min_error=0.1)
        item = e.note("o1", predicted=0.2, actual=0.9)
        d = item.as_dict()
        self.assertEqual(d["id"], "o1")
        self.assertIn("error", d)


if __name__ == "__main__":
    unittest.main()
