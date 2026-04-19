"""Regression: learning_curve under concurrent writes.

Prior to v21, __init__ did `PRAGMA`+`CREATE TABLE`+`CREATE INDEX`
without the instance lock and concurrent records through the connection
could race. This test hammers the tracker from many threads and
asserts every point lands.
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from core.brain import learning_curve as lc


class TestConcurrentRecord(unittest.TestCase):
    def test_many_threads_no_loss(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        t = lc.LearningCurveTracker(Path(tmp.name) / "lc.db")
        n_threads = 8
        per_thread = 25
        barrier = threading.Barrier(n_threads)

        def writer(tid: int) -> None:
            barrier.wait()
            for i in range(per_thread):
                t.record(
                    f"worker_{tid}", "acc",
                    value=float(i) / per_thread,
                    cycle=i + 1,
                )

        threads = [
            threading.Thread(target=writer, args=(i,))
            for i in range(n_threads)
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        for tid in range(n_threads):
            pts = t.points(f"worker_{tid}", "acc", window=per_thread)
            self.assertEqual(
                len(pts), per_thread,
                f"worker_{tid}: expected {per_thread}, got {len(pts)}",
            )
        t.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
