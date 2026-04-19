"""Task prioritizer tests."""
from __future__ import annotations

import time
import unittest

from core.brain import task_prioritizer as tp


class TestTask(unittest.TestCase):
    def test_blank_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            tp.Task(id="", kind="x")

    def test_blank_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            tp.Task(id="x", kind="")

    def test_invalid_blast_raises(self) -> None:
        with self.assertRaises(ValueError):
            tp.Task(id="x", kind="k", blast_radius=0)

    def test_negative_deps_raises(self) -> None:
        with self.assertRaises(ValueError):
            tp.Task(id="x", kind="k", open_dependencies=-1)

    def test_negative_cost_raises(self) -> None:
        with self.assertRaises(ValueError):
            tp.Task(id="x", kind="k", cost_usd=-1)


class TestConfig(unittest.TestCase):
    def test_invalid_weights_raise(self) -> None:
        with self.assertRaises(ValueError):
            tp.TaskPrioritizer(urgency_weight=-1)
        with self.assertRaises(ValueError):
            tp.TaskPrioritizer(cost_scale_usd=0)


class TestUrgency(unittest.TestCase):
    def test_overdue_gets_max_bonus(self) -> None:
        p = tp.TaskPrioritizer()
        now = 1_000_000.0
        t = tp.Task(
            id="late", kind="k", base_value=0.0,
            deadline_ts=now - 3600,
        )
        ranked = p.prioritize([t], now=now)
        self.assertGreater(ranked[0].urgency_bonus, 0.5)

    def test_far_deadline_small_bonus(self) -> None:
        p = tp.TaskPrioritizer()
        now = 1_000_000.0
        t = tp.Task(
            id="ages_off", kind="k", base_value=0.0,
            deadline_ts=now + 100 * 3600,  # 100 hours ahead
        )
        ranked = p.prioritize([t], now=now)
        self.assertLess(ranked[0].urgency_bonus, 0.05)

    def test_no_deadline_zero_bonus(self) -> None:
        p = tp.TaskPrioritizer()
        t = tp.Task(id="no_deadline", kind="k", base_value=1.0)
        ranked = p.prioritize([t])
        self.assertEqual(ranked[0].urgency_bonus, 0.0)


class TestBlastPenalty(unittest.TestCase):
    def test_blast_one_no_penalty(self) -> None:
        p = tp.TaskPrioritizer()
        t = tp.Task(id="narrow", kind="k", blast_radius=1)
        ranked = p.prioritize([t])
        self.assertEqual(ranked[0].blast_penalty, 0.0)

    def test_blast_larger_penalises(self) -> None:
        p = tp.TaskPrioritizer()
        tasks = [
            tp.Task(id="narrow", kind="k", blast_radius=1),
            tp.Task(id="wide", kind="k", blast_radius=100),
        ]
        ranked = p.prioritize(tasks)
        # Narrow should beat wide given same base_value
        self.assertEqual(ranked[0].task.id, "narrow")


class TestDependencies(unittest.TestCase):
    def test_blocked_tasks_penalised(self) -> None:
        p = tp.TaskPrioritizer()
        tasks = [
            tp.Task(id="clear", kind="k", open_dependencies=0),
            tp.Task(id="blocked", kind="k", open_dependencies=5),
        ]
        ranked = p.prioritize(tasks)
        self.assertEqual(ranked[0].task.id, "clear")


class TestCost(unittest.TestCase):
    def test_expensive_task_penalised(self) -> None:
        p = tp.TaskPrioritizer()
        tasks = [
            tp.Task(id="cheap", kind="k", cost_usd=0),
            tp.Task(id="pricey", kind="k", cost_usd=500),
        ]
        ranked = p.prioritize(tasks)
        self.assertEqual(ranked[0].task.id, "cheap")


class TestBaseValue(unittest.TestCase):
    def test_higher_base_wins_otherwise_equal(self) -> None:
        p = tp.TaskPrioritizer()
        tasks = [
            tp.Task(id="low", kind="k", base_value=0.2),
            tp.Task(id="high", kind="k", base_value=0.9),
        ]
        ranked = p.prioritize(tasks)
        self.assertEqual(ranked[0].task.id, "high")


class TestBest(unittest.TestCase):
    def test_best_picks_top_of_ranking(self) -> None:
        p = tp.TaskPrioritizer()
        tasks = [
            tp.Task(id="a", kind="k", base_value=0.5),
            tp.Task(id="b", kind="k", base_value=0.9),
        ]
        self.assertEqual(p.best(tasks).task.id, "b")

    def test_best_none_when_empty(self) -> None:
        p = tp.TaskPrioritizer()
        self.assertIsNone(p.best([]))


class TestTopK(unittest.TestCase):
    def test_top_k_cap(self) -> None:
        p = tp.TaskPrioritizer()
        tasks = [
            tp.Task(id=f"t{i}", kind="k", base_value=float(i))
            for i in range(10)
        ]
        ranked = p.prioritize(tasks, top_k=3)
        self.assertEqual(len(ranked), 3)
        self.assertEqual(ranked[0].task.id, "t9")

    def test_invalid_top_k_raises(self) -> None:
        p = tp.TaskPrioritizer()
        with self.assertRaises(ValueError):
            p.prioritize([], top_k=0)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        p = tp.TaskPrioritizer()
        t = tp.Task(id="x", kind="k", tags=("a",))
        ranked = p.prioritize([t])
        d = ranked[0].as_dict()
        self.assertIn("task", d)
        self.assertIn("score", d)
        self.assertEqual(d["task"]["tags"], ["a"])


class TestConfigReport(unittest.TestCase):
    def test_config_shape(self) -> None:
        p = tp.TaskPrioritizer()
        cfg = p.config()
        self.assertIn("urgency_weight", cfg)
        self.assertIn("cost_scale_usd", cfg)


if __name__ == "__main__":
    unittest.main()
