"""Memory-layer consolidation — distill/compress/contradict/reinforce tests.

Distinct from tests/test_consolidation.py which covers the
cognitive-layer Consolidation phase.
"""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from core.memory import consolidation as cc


def _seed(db: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(db))
    conn.executescript("""
      CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level INTEGER, memory_type TEXT, category TEXT, content TEXT,
        features TEXT, action TEXT, result TEXT, score REAL, confidence REAL,
        tags TEXT, evidence_count INTEGER, use_count INTEGER,
        success_count INTEGER, source_ids TEXT, parent_id INTEGER,
        timestamp REAL, last_used REAL, last_updated REAL
      );
    """)
    for r in rows:
        conn.execute(
            "INSERT INTO memories(level, memory_type, category, content, features,"
            " action, result, score, confidence, tags, evidence_count, use_count,"
            " success_count, source_ids, parent_id, timestamp, last_used,"
            " last_updated) VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                r.get("level", 0),
                r.get("memory_type", "episodic"),
                r.get("category", "x"),
                r.get("content", "{}"),
                "{}",
                r.get("action", "a"),
                "{}",
                r.get("score", 3.0),
                0.5,
                r.get("tags", "[]"),
                1,
                r.get("use_count", 0),
                r.get("success_count", 0),
                "[]",
                0,
                r.get("timestamp", time.time()),
                0, 0,
            ),
        )
    conn.commit()
    conn.close()


class TestCompression(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = cc._DB_PATH
        cc._DB_PATH = Path(self._tmp.name) / "mi.db"

    def tearDown(self) -> None:
        cc._DB_PATH = self._orig
        self._tmp.cleanup()

    def test_old_low_score_dissolves(self) -> None:
        old = time.time() - 40 * 86400
        _seed(cc._DB_PATH, [
            {"category": "x", "score": 1.05, "timestamp": old},
            {"category": "x", "score": 1.05, "timestamp": old},
        ])
        compressed, dissolved = cc._compress_old_events()
        self.assertEqual(compressed, 0)
        self.assertEqual(dissolved, 2)

    def test_new_events_untouched(self) -> None:
        _seed(cc._DB_PATH, [
            {"category": "x", "score": 1.5,
             "timestamp": time.time() - 86400},
        ])
        compressed, dissolved = cc._compress_old_events()
        self.assertEqual(compressed, 0)
        self.assertEqual(dissolved, 0)

    def test_old_midscore_compresses_but_persists(self) -> None:
        old = time.time() - 40 * 86400
        _seed(cc._DB_PATH, [
            {"category": "x", "score": 2.0, "timestamp": old},
        ])
        compressed, dissolved = cc._compress_old_events()
        self.assertEqual(compressed, 1)
        self.assertEqual(dissolved, 0)
        conn = sqlite3.connect(str(cc._DB_PATH))
        score = conn.execute("SELECT score FROM memories").fetchone()[0]
        conn.close()
        self.assertAlmostEqual(score, 1.8, places=2)


class TestContradictions(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = cc._DB_PATH
        cc._DB_PATH = Path(self._tmp.name) / "mi.db"

    def tearDown(self) -> None:
        cc._DB_PATH = self._orig
        self._tmp.cleanup()

    def test_raise_vs_lower_surfaces(self) -> None:
        _seed(cc._DB_PATH, [
            {"level": 2, "category": "pricing", "action": "raise", "score": 4},
            {"level": 2, "category": "pricing", "action": "lower", "score": 4},
        ])
        from unittest.mock import patch, MagicMock
        fake = MagicMock()
        fake.create.return_value = 99
        fake_unified = MagicMock()
        fake_unified.get_memory_intelligence.return_value = fake
        with patch("core.memory.unified_memory.get_unified_memory",
                   return_value=fake_unified):
            n = cc._detect_contradictions()
        self.assertEqual(n, 1)

    def test_aligned_rules_no_contradiction(self) -> None:
        _seed(cc._DB_PATH, [
            {"level": 2, "category": "pricing", "action": "raise", "score": 4},
            {"level": 2, "category": "pricing", "action": "raise", "score": 4},
        ])
        from unittest.mock import patch, MagicMock
        fake = MagicMock()
        fake_unified = MagicMock()
        fake_unified.get_memory_intelligence.return_value = fake
        with patch("core.memory.unified_memory.get_unified_memory",
                   return_value=fake_unified):
            n = cc._detect_contradictions()
        self.assertEqual(n, 0)


class TestReinforcement(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = cc._DB_PATH
        cc._DB_PATH = Path(self._tmp.name) / "mi.db"

    def tearDown(self) -> None:
        cc._DB_PATH = self._orig
        self._tmp.cleanup()

    def test_well_travelled_reinforced(self) -> None:
        _seed(cc._DB_PATH, [
            {"level": 2, "score": 3.0, "use_count": 20, "success_count": 15},
        ])
        self.assertEqual(cc._reinforce_well_travelled(), 1)
        conn = sqlite3.connect(str(cc._DB_PATH))
        score = conn.execute("SELECT score FROM memories").fetchone()[0]
        conn.close()
        self.assertAlmostEqual(score, 3.1, places=2)

    def test_under_threshold_skipped(self) -> None:
        _seed(cc._DB_PATH, [
            {"level": 2, "score": 3.0, "use_count": 2, "success_count": 2},
        ])
        self.assertEqual(cc._reinforce_well_travelled(), 0)


class TestConsolidate(unittest.TestCase):
    def test_returns_report_without_db(self) -> None:
        from pathlib import Path
        orig = cc._DB_PATH
        cc._DB_PATH = Path("/tmp/shopai_nonexistent_v5d1.db")
        try:
            report = cc.consolidate()
            self.assertEqual(report.distilled_patterns, 0)
            self.assertEqual(report.events_compressed, 0)
        finally:
            cc._DB_PATH = orig


if __name__ == "__main__":
    unittest.main()
