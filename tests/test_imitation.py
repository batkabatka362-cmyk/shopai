"""Imitation learning — diff + mining tests with stubbed memory."""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from core.brain import imitation as im


class TestDiff(unittest.TestCase):
    def test_picks_changed_fields(self) -> None:
        d = im.Demonstration(
            id=1, kind="edit",
            before={"title": "A", "price": 10},
            after={"title": "A", "price": 15},
            context={}, timestamp=0,
        )
        diff = d.diff()
        self.assertEqual(list(diff.keys()), ["price"])
        self.assertEqual(diff["price"]["before"], 10)
        self.assertEqual(diff["price"]["after"], 15)

    def test_handles_added_keys(self) -> None:
        d = im.Demonstration(
            id=1, kind="edit",
            before={"title": "A"},
            after={"title": "A", "tone": "urgent"},
            context={}, timestamp=0,
        )
        diff = d.diff()
        self.assertIn("tone", diff)


class TestMining(unittest.TestCase):
    def test_mines_majority_action(self) -> None:
        now = time.time()
        demos = [
            im.Demonstration(id=1, kind="override",
                              before={"tone": "friendly"},
                              after={"tone": "urgent"},
                              context={"niche": "electronics"}, timestamp=now),
            im.Demonstration(id=2, kind="override",
                              before={"tone": "friendly"},
                              after={"tone": "urgent"},
                              context={"niche": "electronics"}, timestamp=now),
            im.Demonstration(id=3, kind="override",
                              before={"tone": "friendly"},
                              after={"tone": "urgent"},
                              context={"niche": "electronics"}, timestamp=now),
        ]
        with patch.object(im, "_load_demonstrations", return_value=demos), \
             patch.object(im, "_persist_rule"):
            rules = im.mine()
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].action.get("tone"), "urgent")
        self.assertEqual(rules[0].evidence, 3)
        self.assertIn("electronics", rules[0].trigger.get("niche", ""))

    def test_below_min_evidence_dropped(self) -> None:
        demos = [
            im.Demonstration(id=1, kind="edit",
                              before={"x": 1}, after={"x": 2},
                              context={}, timestamp=0),
            im.Demonstration(id=2, kind="edit",
                              before={"x": 1}, after={"x": 2},
                              context={}, timestamp=0),
        ]  # only 2 — below threshold
        with patch.object(im, "_load_demonstrations", return_value=demos), \
             patch.object(im, "_persist_rule"):
            rules = im.mine()
        self.assertEqual(rules, [])

    def test_inconsistent_after_values_dropped(self) -> None:
        demos = [
            im.Demonstration(id=i, kind="edit",
                              before={"x": 1},
                              after={"x": v},
                              context={}, timestamp=0)
            for i, v in enumerate([2, 3, 4])  # all different afters
        ]
        with patch.object(im, "_load_demonstrations", return_value=demos), \
             patch.object(im, "_persist_rule"):
            rules = im.mine()
        # No key had >=60% agreement → no rule emitted
        self.assertEqual(rules, [])


class TestRecord(unittest.TestCase):
    def test_record_returns_id(self) -> None:
        from unittest.mock import MagicMock
        fake_mi = MagicMock()
        fake_mi.create.return_value = 42
        fake_unified = MagicMock()
        fake_unified.get_memory_intelligence.return_value = fake_mi
        with patch("core.memory.unified_memory.get_unified_memory",
                   return_value=fake_unified):
            mid = im.record_demonstration(
                "override",
                before={"a": 1}, after={"a": 2},
                context={"niche": "x"},
            )
        self.assertEqual(mid, 42)
        fake_mi.create.assert_called_once()

    def test_record_swallows_exception(self) -> None:
        with patch("core.memory.unified_memory.get_unified_memory",
                   side_effect=RuntimeError("boom")):
            mid = im.record_demonstration("x", {}, {})
        self.assertEqual(mid, 0)


if __name__ == "__main__":
    unittest.main()
