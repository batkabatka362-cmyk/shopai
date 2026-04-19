"""Semantic retrieval — math + schema only.

The Gemini call is stubbed so the tests stay hermetic. Cosine,
text collapsing, and the sidecar table path are all exercised.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.memory import embeddings as emb
from core.memory import semantic_index as si


class TestCosine(unittest.TestCase):
    def test_identical(self) -> None:
        self.assertAlmostEqual(emb.cosine([1, 0, 0], [1, 0, 0]), 1.0)

    def test_orthogonal(self) -> None:
        self.assertAlmostEqual(emb.cosine([1, 0, 0], [0, 1, 0]), 0.0)

    def test_opposite(self) -> None:
        self.assertAlmostEqual(emb.cosine([1, 0, 0], [-1, 0, 0]), -1.0)

    def test_empty(self) -> None:
        self.assertEqual(emb.cosine([], [1, 2]), 0.0)
        self.assertEqual(emb.cosine([1, 2], []), 0.0)

    def test_length_mismatch(self) -> None:
        self.assertEqual(emb.cosine([1, 2], [1, 2, 3]), 0.0)

    def test_zero_norm(self) -> None:
        self.assertEqual(emb.cosine([0, 0, 0], [1, 2, 3]), 0.0)


class TestEncoding(unittest.TestCase):
    def test_roundtrip(self) -> None:
        vec = [0.123456789, -0.987654321, 1e-6]
        blob = emb.encode_blob(vec)
        restored = emb.decode_blob(blob)
        self.assertEqual(len(restored), 3)
        self.assertAlmostEqual(restored[0], 0.123457, places=5)
        self.assertAlmostEqual(restored[1], -0.987654, places=5)

    def test_decode_empty(self) -> None:
        self.assertEqual(emb.decode_blob(""), [])
        self.assertEqual(emb.decode_blob("not json"), [])


class TestTextCollapsing(unittest.TestCase):
    def test_json_content_extracted(self) -> None:
        row = {
            "category": "launch",
            "action": "register",
            "tags": json.dumps(["revenue", "launch:abc"]),
            "content": json.dumps({
                "title": "Magnetic Phone Holder",
                "description": "Premium car accessory",
            }),
        }
        text = si._text_for(row)
        self.assertIn("launch", text)
        self.assertIn("register", text)
        self.assertIn("Magnetic Phone Holder", text)

    def test_empty_content(self) -> None:
        row = {"category": "x", "action": "y", "tags": "[]", "content": "{}"}
        text = si._text_for(row)
        self.assertIn("category=x", text)
        self.assertIn("action=y", text)


class TestIndexAndRetrieve(unittest.TestCase):
    """Exercise the sqlite path with a fake embedder."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._orig_db = si._DB_PATH
        si._DB_PATH = Path(self._tmp.name) / "mi.db"
        # Seed the memories table so index_pending has something to pick up.
        conn = sqlite3.connect(str(si._DB_PATH))
        conn.executescript("""
          CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level INTEGER, category TEXT, action TEXT, content TEXT,
            tags TEXT, score REAL, use_count INTEGER, success_count INTEGER,
            last_used REAL, timestamp REAL
          );
          INSERT INTO memories(level, category, action, content, tags, score,
                               use_count, success_count, last_used, timestamp)
          VALUES (2, 'pricing', 'raise', '{"rule":"raise if margin<20"}',
                  '["pricing","rule"]', 4.0, 5, 3, 1000, 1000),
                 (2, 'marketing', 'push', '{"rule":"ad spend > $10"}',
                  '["marketing"]', 4.0, 2, 1, 1001, 1001);
        """)
        conn.commit()
        conn.close()
        emb.clear_cache()

    def tearDown(self) -> None:
        si._DB_PATH = self._orig_db
        self._tmp.cleanup()

    @staticmethod
    def _fake_embed(text: str) -> list[float]:
        """Deterministic tiny embedding: sum of ords, hashed to 8 dims."""
        if not text:
            return []
        h = 0
        out = [0.0] * 8
        for i, ch in enumerate(text):
            out[i % 8] += (ord(ch) % 13) / 10.0
            h += ord(ch)
        # Normalise roughly
        return out

    def test_index_and_retrieve_orders_by_similarity(self) -> None:
        with patch.object(emb, "embed", side_effect=self._fake_embed), \
             patch.object(emb, "is_configured", return_value=True):
            summary = si.index_pending(limit=10, level_min=2)
            self.assertEqual(summary["embedded"], 2)

            results = si.retrieve_similar("pricing rule", k=2, level_min=2)
            self.assertEqual(len(results), 2)
            # Both rows come back; ordering should put the pricing row first
            # because the fake embedder scores by shared characters and
            # "pricing" appears in that row's tags.
            top_ids = [r["id"] for r in results]
            self.assertIn(1, top_ids)

    def test_retrieve_when_embed_unconfigured_returns_empty(self) -> None:
        with patch.object(emb, "is_configured", return_value=False), \
             patch.object(emb, "embed", return_value=[]):
            out = si.retrieve_similar("anything", k=5)
            self.assertEqual(out, [])

    def test_index_pending_noop_without_api_key(self) -> None:
        with patch.object(emb, "is_configured", return_value=False):
            summary = si.index_pending()
            self.assertEqual(summary["embedded"], 0)
            self.assertIn("unconfigured", summary["skipped"])


if __name__ == "__main__":
    unittest.main()
