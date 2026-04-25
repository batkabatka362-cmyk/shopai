"""Feature store tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.memory import feature_store as fs


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = fs.FeatureStore(Path(self._tmp.name) / "f.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_and_get(self) -> None:
        self.store.register(
            "constant", lambda eid: 42,
        )
        self.assertEqual(self.store.get("constant", "x"), 42)

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.store.register("", lambda eid: 1)

    def test_unknown_feature_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.store.get("missing", "x")


class TestCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = fs.FeatureStore(Path(self._tmp.name) / "f.db")
        self.calls = 0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _count(self, eid):
        self.calls += 1
        return {"eid": eid, "call": self.calls}

    def test_cache_hit_avoids_recompute(self) -> None:
        self.store.register("f", self._count, ttl_s=60)
        v1 = self.store.get("f", "x")
        v2 = self.store.get("f", "x")
        self.assertEqual(v1, v2)
        self.assertEqual(self.calls, 1)

    def test_ttl_expiry_recomputes(self) -> None:
        self.store.register("f", self._count, ttl_s=0.01)
        self.store.get("f", "x")
        time.sleep(0.05)
        self.store.get("f", "x")
        self.assertEqual(self.calls, 2)

    def test_force_recomputes(self) -> None:
        self.store.register("f", self._count, ttl_s=3600)
        self.store.get("f", "x")
        self.store.get("f", "x", force=True)
        self.assertEqual(self.calls, 2)

    def test_version_bump_recomputes(self) -> None:
        self.store.register("f", self._count, ttl_s=3600, version=1)
        self.store.get("f", "x")
        self.store.register("f", self._count, ttl_s=3600, version=2)
        self.store.get("f", "x")
        self.assertEqual(self.calls, 2)


class TestBatchGet(unittest.TestCase):
    def test_batch_returns_dict(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        store = fs.FeatureStore(Path(tmp.name) / "f.db")
        store.register("f", lambda eid: int(eid) * 2)
        out = store.batch_get("f", ["1", "2", "3"])
        self.assertEqual(out, {"1": 2, "2": 4, "3": 6})
        tmp.cleanup()


class TestInvalidate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = fs.FeatureStore(Path(self._tmp.name) / "f.db")
        self.store.register("f", lambda eid: eid, ttl_s=3600)
        self.store.register("g", lambda eid: eid, ttl_s=3600)
        for eid in ("a", "b"):
            self.store.get("f", eid)
            self.store.get("g", eid)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_invalidate_feature(self) -> None:
        removed = self.store.invalidate(feature="f")
        self.assertEqual(removed, 2)

    def test_invalidate_entity(self) -> None:
        removed = self.store.invalidate(entity_id="a")
        self.assertEqual(removed, 2)

    def test_invalidate_feature_and_entity(self) -> None:
        removed = self.store.invalidate(feature="f", entity_id="a")
        self.assertEqual(removed, 1)

    def test_invalidate_all(self) -> None:
        removed = self.store.invalidate()
        self.assertEqual(removed, 4)


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        store = fs.FeatureStore(Path(tmp.name) / "f.db")
        store.register("f", lambda eid: 1)
        store.register("g", lambda eid: 2)
        store.get("f", "a")
        store.get("g", "a")
        stats = store.stats()
        self.assertEqual(stats["total_rows"], 2)
        self.assertEqual(stats["by_feature"].get("f"), 1)
        self.assertIn("f", stats["registered"])
        tmp.cleanup()


class TestMetadata(unittest.TestCase):
    def test_get_with_metadata_returns_entry(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        store = fs.FeatureStore(Path(tmp.name) / "f.db")
        store.register("f", lambda eid: {"v": 1})
        meta = store.get_with_metadata("f", "x")
        self.assertIsNotNone(meta)
        self.assertEqual(meta.value["v"], 1)
        self.assertGreaterEqual(meta.age_s, 0)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
