"""Brain benchmark tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import benchmark as bm


class TestBuiltinTasks(unittest.TestCase):
    def test_sentiment_task_scores_high(self) -> None:
        r = bm.task_sentiment_accuracy()
        self.assertGreater(r.score, 0.5)

    def test_bayesnet_task_correct(self) -> None:
        r = bm.task_bayesnet_inference()
        self.assertEqual(r.score, 1.0)

    def test_conflict_pick_correct(self) -> None:
        r = bm.task_rule_conflict_pick()
        self.assertEqual(r.score, 1.0)

    def test_attribution_sanity_correct(self) -> None:
        r = bm.task_attribution_sanity()
        self.assertEqual(r.score, 1.0)

    def test_ethics_block_correct(self) -> None:
        r = bm.task_ethics_block()
        self.assertEqual(r.score, 1.0)


class TestRunAll(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.b = bm.BrainBenchmark(Path(self._tmp.name) / "b.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_run_all_produces_report(self) -> None:
        report = self.b.run_all()
        self.assertGreater(len(report.tasks), 0)
        self.assertGreaterEqual(report.overall, 0.0)
        self.assertLessEqual(report.overall, 1.0)

    def test_report_every_task_has_duration(self) -> None:
        report = self.b.run_all()
        for t in report.tasks:
            self.assertGreaterEqual(t.duration_ms, 0.0)

    def test_exceptions_do_not_crash_run(self) -> None:
        def broken():
            raise RuntimeError("boom")
        self.b.add_task(broken)
        report = self.b.run_all()
        broken_task = next(
            (t for t in report.tasks if t.name == "broken"),
            None,
        )
        self.assertIsNotNone(broken_task)
        self.assertEqual(broken_task.score, 0.0)


class TestAddTask(unittest.TestCase):
    def test_custom_task_runs(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        b = bm.BrainBenchmark(Path(tmp.name) / "b.db")
        def my_task():
            return bm.TaskResult(name="my_task", score=0.8)
        b.add_task(my_task)
        self.assertIn("my_task", [
            t.replace("task_", "") for t in b.task_names()
        ])
        report = b.run_all()
        self.assertTrue(any(t.name == "my_task" for t in report.tasks))
        tmp.cleanup()


class TestPersistence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.b = bm.BrainBenchmark(Path(self._tmp.name) / "b.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_persist_and_history(self) -> None:
        r = self.b.run_all()
        self.b.persist(r, label="first")
        history = self.b.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["label"], "first")

    def test_latest_returns_most_recent(self) -> None:
        r1 = self.b.run_all()
        self.b.persist(r1, label="a")
        time.sleep(0.01)
        r2 = self.b.run_all()
        self.b.persist(r2, label="b")
        latest = self.b.latest()
        self.assertEqual(latest["label"], "b")

    def test_growth_requires_two_runs(self) -> None:
        self.b.persist(self.b.run_all(), label="one")
        self.assertIsNone(self.b.growth())
        time.sleep(0.01)
        self.b.persist(self.b.run_all(), label="two")
        g = self.b.growth()
        self.assertIsNotNone(g)
        self.assertEqual(g["runs"], 2)


class TestTaskResult(unittest.TestCase):
    def test_score_clamps_in_safe(self) -> None:
        self.assertEqual(bm._safe(1.5), 1.0)
        self.assertEqual(bm._safe(-0.1), 0.0)
        self.assertEqual(bm._safe(0.5), 0.5)


if __name__ == "__main__":
    unittest.main()
