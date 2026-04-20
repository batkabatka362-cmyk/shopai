"""Manual seed source tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agents.research.sources import manual_seed as ms


class _TmpFile:
    """Helper for tests — creates a temp file path and removes it."""
    def __init__(self):
        self._tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        )
        self._tmp.close()
        self.path = Path(self._tmp.name)

    def write(self, data):
        self.path.write_text(
            json.dumps(data) if not isinstance(data, str) else data,
        )

    def cleanup(self):
        if self.path.exists():
            self.path.unlink()


class TestAvailable(unittest.TestCase):
    def test_not_available_when_missing(self):
        src = ms.ManualSeedSource("/nonexistent/seeds.json")
        self.assertFalse(src.is_available())

    def test_available_when_exists(self):
        f = _TmpFile()
        f.write({"winners": []})
        try:
            src = ms.ManualSeedSource(f.path)
            self.assertTrue(src.is_available())
        finally:
            f.cleanup()


class TestFetch(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        src = ms.ManualSeedSource("/nope/seeds.json")
        self.assertEqual(src.fetch(), [])
        self.assertIn(
            "missing", src.stats()["last_error"],
        )

    def test_invalid_json_returns_empty(self):
        f = _TmpFile()
        f.write("{this is not json")
        try:
            src = ms.ManualSeedSource(f.path)
            self.assertEqual(src.fetch(), [])
            self.assertIn(
                "parse failed", src.stats()["last_error"],
            )
        finally:
            f.cleanup()

    def test_wrong_shape_returns_empty(self):
        f = _TmpFile()
        f.write(42)  # top-level is not a list or dict with 'winners'
        try:
            src = ms.ManualSeedSource(f.path)
            self.assertEqual(src.fetch(), [])
            self.assertIn(
                "top-level", src.stats()["last_error"],
            )
        finally:
            f.cleanup()

    def test_top_level_list_accepted(self):
        f = _TmpFile()
        f.write([
            {"title": "A", "price": 10},
            {"title": "B", "price": 20},
        ])
        try:
            src = ms.ManualSeedSource(f.path)
            out = src.fetch()
            self.assertEqual(len(out), 2)
            titles = [c.title for c in out]
            self.assertEqual(titles, ["A", "B"])
        finally:
            f.cleanup()

    def test_wrapped_list_accepted(self):
        f = _TmpFile()
        f.write({"winners": [{"title": "X", "price": 5}]})
        try:
            src = ms.ManualSeedSource(f.path)
            self.assertEqual(len(src.fetch()), 1)
        finally:
            f.cleanup()

    def test_missing_title_skipped(self):
        f = _TmpFile()
        f.write([
            {"title": "", "price": 10},  # blank title
            {"price": 10},               # no title
            {"title": "Keep", "price": 10},
        ])
        try:
            src = ms.ManualSeedSource(f.path)
            out = src.fetch()
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0].title, "Keep")
        finally:
            f.cleanup()

    def test_type_error_skipped(self):
        f = _TmpFile()
        f.write([
            {"title": "Bad price", "price": "not-a-number"},
            {"title": "Good", "price": 10},
        ])
        try:
            src = ms.ManualSeedSource(f.path)
            out = src.fetch()
            titles = [c.title for c in out]
            self.assertEqual(titles, ["Good"])
        finally:
            f.cleanup()

    def test_saturation_clamped(self):
        f = _TmpFile()
        f.write([
            {"title": "X", "saturation_score": 2.5},
            {"title": "Y", "saturation_score": -1.0},
        ])
        try:
            src = ms.ManualSeedSource(f.path)
            out = src.fetch()
            sats = [c.saturation_score for c in out]
            self.assertEqual(sats, [1.0, 0.0])
        finally:
            f.cleanup()

    def test_limit_honored(self):
        f = _TmpFile()
        f.write([
            {"title": f"p{i}", "price": 10}
            for i in range(5)
        ])
        try:
            src = ms.ManualSeedSource(f.path)
            self.assertEqual(len(src.fetch(limit=3)), 3)
        finally:
            f.cleanup()

    def test_non_dict_entries_skipped(self):
        f = _TmpFile()
        f.write([
            "not a dict",
            42,
            {"title": "Good", "price": 10},
        ])
        try:
            src = ms.ManualSeedSource(f.path)
            out = src.fetch()
            self.assertEqual(len(out), 1)
        finally:
            f.cleanup()

    def test_default_source_override(self):
        f = _TmpFile()
        f.write([{"title": "X", "price": 5}])
        try:
            src = ms.ManualSeedSource(
                f.path, default_source="my_curation",
            )
            out = src.fetch()
            self.assertEqual(out[0].source, "my_curation")
        finally:
            f.cleanup()

    def test_per_entry_source_wins(self):
        f = _TmpFile()
        f.write([
            {
                "title": "X", "price": 5,
                "source": "tiktok_shop",
            },
        ])
        try:
            src = ms.ManualSeedSource(
                f.path, default_source="my_curation",
            )
            out = src.fetch()
            self.assertEqual(out[0].source, "tiktok_shop")
        finally:
            f.cleanup()

    def test_tags_and_external_id_preserved(self):
        f = _TmpFile()
        f.write([
            {
                "title": "X", "price": 5,
                "tags": ["a", "b"],
                "external_id": "ali-123",
            },
        ])
        try:
            src = ms.ManualSeedSource(f.path)
            out = src.fetch()
            self.assertEqual(out[0].tags, ("a", "b"))
            self.assertEqual(out[0].external_id, "ali-123")
        finally:
            f.cleanup()


class TestHotReload(unittest.TestCase):
    def test_file_replaced_picked_up(self):
        f = _TmpFile()
        f.write([{"title": "A"}])
        try:
            src = ms.ManualSeedSource(f.path)
            self.assertEqual(len(src.fetch()), 1)
            # Rewrite — next fetch sees the change
            f.write([
                {"title": "B"}, {"title": "C"},
            ])
            self.assertEqual(len(src.fetch()), 2)
        finally:
            f.cleanup()


class TestWriteTemplate(unittest.TestCase):
    def test_template_is_valid(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            target = Path(tmp.name) / "seeds.json"
            written = ms.write_seed_template(target)
            self.assertTrue(written.exists())
            data = json.loads(written.read_text())
            self.assertIn("winners", data)
            self.assertGreater(len(data["winners"]), 0)
        finally:
            tmp.cleanup()

    def test_template_readable_by_source(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            target = Path(tmp.name) / "seeds.json"
            ms.write_seed_template(target)
            src = ms.ManualSeedSource(target)
            out = src.fetch()
            # The example in the template is a valid entry
            self.assertGreater(len(out), 0)
        finally:
            tmp.cleanup()


class TestIntegrationWithWinnerSearcher(unittest.TestCase):
    """Confirm the source plugs cleanly into WinnerSearcher."""

    def test_seeded_search(self):
        from agents.research.winner_searcher import (
            WinnerSearcher,
        )
        from core.memory.knowledge_base import KnowledgeBase
        tmp = tempfile.TemporaryDirectory()
        try:
            seeds = Path(tmp.name) / "seeds.json"
            seeds.write_text(json.dumps([
                {
                    "title": "Pet Bowl",
                    "price": 30, "cost": 10,
                    "daily_sales": 20,
                    "saturation_score": 0.3,
                },
            ]))
            kb = KnowledgeBase(
                db_path=Path(tmp.name) / "k.db",
            )
            searcher = WinnerSearcher(
                sources=[ms.ManualSeedSource(seeds)],
                knowledge_base=kb,
            )
            result = searcher.search(top_n=5, publish=False)
            self.assertEqual(len(result.ranked), 1)
            self.assertIn("manual_seed", result.sources_used)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
