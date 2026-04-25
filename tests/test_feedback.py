"""Feedback loop — up/down vote + summary tests."""
from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.brain import feedback as fb


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = fb._DB_PATH
        fb._DB_PATH = Path(self._tmp.name) / "mi.db"
        conn = sqlite3.connect(str(fb._DB_PATH))
        conn.executescript("""
          CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            score REAL,
            last_updated REAL,
            category TEXT
          );
          INSERT INTO memories(id, score, last_updated, category)
          VALUES (42, 3.0, 0, 'pricing');
        """)
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        fb._DB_PATH = self._orig
        self._tmp.cleanup()

    def test_up_vote_raises_score(self) -> None:
        with patch("core.memory.unified_memory.get_unified_memory"):
            result = fb.record(42, +1, "good call")
        self.assertEqual(result.sign, 1)
        self.assertEqual(result.prior_score, 3.0)
        self.assertAlmostEqual(result.new_score, 3.25)

    def test_down_vote_lowers_score(self) -> None:
        with patch("core.memory.unified_memory.get_unified_memory"):
            result = fb.record(42, -1, "bad call")
        self.assertAlmostEqual(result.new_score, 2.6)

    def test_zero_sign_is_noop(self) -> None:
        with patch("core.memory.unified_memory.get_unified_memory"):
            result = fb.record(42, 0, "neutral")
        self.assertEqual(result.prior_score, 0.0)
        self.assertEqual(result.new_score, 0.0)

    def test_unknown_memory_noop(self) -> None:
        with patch("core.memory.unified_memory.get_unified_memory"):
            result = fb.record(9999, +1)
        self.assertIsNone(result.feedback_memory_id)
        self.assertEqual(result.prior_score, 0.0)

    def test_score_clamped_to_max(self) -> None:
        # Artificially inflate
        conn = sqlite3.connect(str(fb._DB_PATH))
        conn.execute("UPDATE memories SET score=4.9 WHERE id=42")
        conn.commit()
        conn.close()
        with patch("core.memory.unified_memory.get_unified_memory"):
            result = fb.record(42, +1)
        self.assertLessEqual(result.new_score, 5.0)

    def test_score_clamped_to_min(self) -> None:
        conn = sqlite3.connect(str(fb._DB_PATH))
        conn.execute("UPDATE memories SET score=1.1 WHERE id=42")
        conn.commit()
        conn.close()
        with patch("core.memory.unified_memory.get_unified_memory"):
            result = fb.record(42, -1)
        self.assertGreaterEqual(result.new_score, 1.0)


class TestSummarise(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = fb._DB_PATH
        fb._DB_PATH = Path(self._tmp.name) / "mi.db"
        conn = sqlite3.connect(str(fb._DB_PATH))
        conn.executescript("""
          CREATE TABLE memories (
            id INTEGER PRIMARY KEY,
            score REAL, last_updated REAL,
            category TEXT, content TEXT
          );
          INSERT INTO memories(id, score, last_updated, category, content)
          VALUES (1, 3.5, 0, 'pricing', '{}'),
                 (2, 3.0, 0, 'marketing', '{}'),
                 (3, 4.0, 0, 'feedback',
                  '{"target_memory_id":1,"sign":1,"note":"good"}'),
                 (4, 4.0, 0, 'feedback',
                  '{"target_memory_id":2,"sign":-1,"note":"bad"}');
        """)
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        fb._DB_PATH = self._orig
        self._tmp.cleanup()

    def test_summarise_counts(self) -> None:
        s = fb.summarise()
        self.assertEqual(s.total, 2)
        self.assertEqual(s.up_votes, 1)
        self.assertEqual(s.down_votes, 1)
        self.assertEqual(s.categories_up, {"pricing": 1})
        self.assertEqual(s.categories_down, {"marketing": 1})


if __name__ == "__main__":
    unittest.main()
