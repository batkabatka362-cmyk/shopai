"""Narrative sense-maker tests."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from core.brain import narrative as nr


def _seed(db_path: Path, rows: list[dict]) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT, action TEXT, score REAL, level INTEGER,
        content TEXT, timestamp REAL
      );
    """)
    now = time.time()
    for r in rows:
        conn.execute(
            "INSERT INTO memories (category, action, score, level, "
            "content, timestamp) VALUES (?,?,?,?,?,?)",
            (r.get("category"), r.get("action"),
             r.get("score", 3.0), r.get("level", 0),
             json.dumps(r.get("content") or {}),
             r.get("timestamp", now)),
        )
    conn.commit()
    conn.close()


class TestComposeWeek(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "m.db"
        _seed(self.db, [
            {"category": "launch", "action": "scaled",
             "content": {"launch_id": "L1"}, "score": 4.0},
            {"category": "launch", "action": "killed",
             "content": {"launch_id": "L2"}, "score": 3.0},
            {"category": "feedback", "action": "up",
             "content": {"sign": 1, "note": "good"}, "score": 4.5},
            {"category": "feedback", "action": "down",
             "content": {"sign": -1, "note": "bad"}, "score": 4.5},
            {"category": "hypothesis", "action": "resolved_confirmed",
             "content": {"subject": "price_bump"}, "score": 3.5},
            {"category": "transfer_strategy", "action": "mined",
             "content": {"feature": "tone:luxury"}, "score": 4.0},
            {"category": "contradiction", "action": "pricing",
             "content": {}, "score": 3.0},
        ])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_all_buckets_populated(self) -> None:
        story = nr.compose_week(db_path=self.db)
        self.assertEqual(len(story.wins), 2)          # scaled + up-vote
        self.assertEqual(len(story.setbacks), 2)      # killed + down-vote
        self.assertEqual(len(story.bets), 1)
        self.assertEqual(len(story.lessons), 1)
        self.assertEqual(len(story.open_loops), 1)

    def test_older_than_week_excluded(self) -> None:
        _seed(self.db, [
            {"category": "launch", "action": "scaled",
             "content": {"launch_id": "ancient"},
             "timestamp": time.time() - 30 * 86_400},
        ])
        story = nr.compose_week(db_path=self.db)
        ids = [w.headline for w in story.wins]
        self.assertFalse(any("ancient" in h for h in ids))

    def test_empty_db_returns_empty_story(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        missing_db = Path(tmp.name) / "none.db"
        story = nr.compose_week(db_path=missing_db)
        self.assertEqual(len(story.wins), 0)
        tmp.cleanup()


class TestRendering(unittest.TestCase):
    def test_markdown_contains_sections(self) -> None:
        story = nr.Story(period="2026-04-13..2026-04-19")
        story.wins.append(nr.StoryItem("win", "scaled L1"))
        story.setbacks.append(nr.StoryItem("setback", "killed L2"))
        md = story.to_markdown()
        self.assertIn("Wins", md)
        self.assertIn("scaled L1", md)
        self.assertIn("Setbacks", md)

    def test_as_dict_has_totals(self) -> None:
        story = nr.Story(period="x")
        story.wins.append(nr.StoryItem("win", "a"))
        story.wins.append(nr.StoryItem("win", "b"))
        d = story.as_dict()
        self.assertEqual(d["totals"]["wins"], 2)


class TestTrim(unittest.TestCase):
    def test_trims_to_five_per_bucket_by_score(self) -> None:
        story = nr.Story(period="x")
        for i in range(10):
            story.wins.append(nr.StoryItem("win", f"w{i}", score=float(i)))
        nr._trim(story, per_bucket=5)
        self.assertEqual(len(story.wins), 5)
        # Top 5 by score → 9..5
        headlines = [w.headline for w in story.wins]
        self.assertEqual(headlines[0], "w9")
        self.assertEqual(headlines[-1], "w5")


if __name__ == "__main__":
    unittest.main()
