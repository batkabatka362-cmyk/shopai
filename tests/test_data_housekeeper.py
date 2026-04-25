"""Data housekeeper tests."""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from core.memory import data_housekeeper as dh


def _seed_memories_db(path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
      CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        score REAL, timestamp REAL, category TEXT, content TEXT
      );
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO memories (score, timestamp, category, content) "
            "VALUES (?,?,?,?)",
            (r.get("score", 3.0), r.get("timestamp", time.time()),
             r.get("category", "x"), r.get("content", "{}")),
        )
    conn.commit()
    conn.close()


class TestPruneOld(unittest.TestCase):
    def test_prunes_low_score_old_rows(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db = Path(tmp.name) / "memory_intelligence.db"
        now = time.time()
        _seed_memories_db(db, [
            {"score": 0.5, "timestamp": now - 365 * 86_400},  # old + low
            {"score": 0.5, "timestamp": now},                   # recent low
            {"score": 3.0, "timestamp": now - 365 * 86_400},   # old + high
            {"score": 3.0, "timestamp": now},                   # recent high
        ])
        house = dh.DataHousekeeper(
            targets=[(str(db), {
                "table": "memories",
                "keep_days": 180, "score_floor": 1.5,
            })],
            checkpoint_dir=Path(tmp.name) / "checkpoints",
        )
        report = house.run()
        # Only row with BOTH old AND low score should be pruned
        self.assertEqual(report.tables[0].rows_before, 4)
        self.assertEqual(report.tables[0].rows_after, 3)
        tmp.cleanup()

    def test_no_criteria_no_prune(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db = Path(tmp.name) / "m.db"
        _seed_memories_db(db, [{"score": 0.1} for _ in range(5)])
        house = dh.DataHousekeeper(
            targets=[(str(db), {"table": "memories"})],
            checkpoint_dir=Path(tmp.name) / "checkpoints",
        )
        report = house.run()
        self.assertEqual(report.tables[0].rows_after, 5)
        tmp.cleanup()


class TestMissingDb(unittest.TestCase):
    def test_missing_db_reported_as_error(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        house = dh.DataHousekeeper(
            targets=[("does/not/exist.db", {"table": "x"})],
            checkpoint_dir=Path(tmp.name) / "checkpoints",
        )
        report = house.run()
        self.assertEqual(report.tables[0].error, "missing")
        self.assertEqual(report.tables[0].rows_before, 0)
        tmp.cleanup()


class TestVacuum(unittest.TestCase):
    def test_vacuum_reclaims_bytes_after_delete(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db = Path(tmp.name) / "m.db"
        # Make a file big enough that VACUUM actually shrinks it
        _seed_memories_db(db, [
            {"score": 0.1, "content": "x" * 1000,
             "timestamp": time.time() - 365 * 86_400}
            for _ in range(100)
        ])
        house = dh.DataHousekeeper(
            targets=[(str(db), {
                "table": "memories",
                "keep_days": 30, "score_floor": 1.5,
            })],
            checkpoint_dir=Path(tmp.name) / "checkpoints",
        )
        report = house.run()
        self.assertGreater(report.tables[0].bytes_reclaimed, 0)
        tmp.cleanup()


class TestCheckpointPrune(unittest.TestCase):
    def test_prunes_beyond_keep_last(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        ckpt_dir = Path(tmp.name) / "checkpoints"
        ckpt_dir.mkdir()
        # Create 5 fake archives with varying mtimes
        archives = []
        for i in range(5):
            p = ckpt_dir / f"snap_{i}.tar.gz"
            p.write_bytes(b"archive")
            # Set mtime so older ones have earlier timestamps
            import os
            ts = time.time() - (5 - i) * 100
            os.utime(p, (ts, ts))
            archives.append(p)
        house = dh.DataHousekeeper(
            targets=[],
            checkpoint_dir=ckpt_dir,
            keep_checkpoints=2,
        )
        report = house.run()
        self.assertEqual(report.checkpoints_pruned, 3)
        remaining = list(ckpt_dir.glob("*.tar.gz"))
        self.assertEqual(len(remaining), 2)
        tmp.cleanup()

    def test_no_checkpoint_dir_zero_pruned(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        house = dh.DataHousekeeper(
            targets=[],
            checkpoint_dir=Path(tmp.name) / "nonexistent",
        )
        report = house.run()
        self.assertEqual(report.checkpoints_pruned, 0)
        tmp.cleanup()


class TestReport(unittest.TestCase):
    def test_total_bytes_reclaimed_sums_per_table(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        db = Path(tmp.name) / "m.db"
        _seed_memories_db(db, [
            {"score": 0.1, "content": "x" * 500,
             "timestamp": time.time() - 365 * 86_400}
            for _ in range(50)
        ])
        house = dh.DataHousekeeper(
            targets=[(str(db), {
                "table": "memories",
                "keep_days": 30, "score_floor": 1.5,
            })],
            checkpoint_dir=Path(tmp.name) / "checkpoints",
        )
        report = house.run()
        self.assertGreaterEqual(
            report.total_bytes_reclaimed,
            report.tables[0].bytes_reclaimed,
        )
        tmp.cleanup()

    def test_as_dict_roundtrip(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        house = dh.DataHousekeeper(
            targets=[],
            checkpoint_dir=Path(tmp.name) / "c",
        )
        d = house.run().as_dict()
        self.assertIn("tables", d)
        self.assertIn("checkpoints_pruned", d)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
