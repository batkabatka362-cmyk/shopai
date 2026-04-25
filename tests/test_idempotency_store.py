"""Idempotency store tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.system import idempotency_store as ids


class TestExecute(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.s = ids.IdempotencyStore(Path(self._tmp.name) / "i.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_call_runs_fn(self) -> None:
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            return "ok"
        self.assertEqual(self.s.execute("shopify", "k1", fn), "ok")
        self.assertEqual(calls["n"], 1)

    def test_repeat_call_returns_cached(self) -> None:
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            return {"order_id": 42}
        self.s.execute("shopify", "k1", fn)
        self.s.execute("shopify", "k1", fn)
        self.s.execute("shopify", "k1", fn)
        self.assertEqual(calls["n"], 1)

    def test_distinct_keys_each_run(self) -> None:
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            return calls["n"]
        self.s.execute("shopify", "a", fn)
        self.s.execute("shopify", "b", fn)
        self.assertEqual(calls["n"], 2)

    def test_distinct_namespaces_isolated(self) -> None:
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            return calls["n"]
        self.s.execute("shopify", "k", fn)
        self.s.execute("meta", "k", fn)
        self.assertEqual(calls["n"], 2)

    def test_error_not_cached_by_default(self) -> None:
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            raise RuntimeError("transient")
        with self.assertRaises(RuntimeError):
            self.s.execute("x", "y", fn)
        with self.assertRaises(RuntimeError):
            self.s.execute("x", "y", fn)
        self.assertEqual(calls["n"], 2)

    def test_cache_errors_flag(self) -> None:
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            raise RuntimeError("permanent")
        with self.assertRaises(RuntimeError):
            self.s.execute("x", "y", fn, cache_errors=True)
        self.assertTrue(self.s.seen("x", "y"))

    def test_ttl_expiry(self) -> None:
        def fn():
            return "v"
        self.s.execute("x", "y", fn, ttl_s=0.05)
        time.sleep(0.1)
        self.assertIsNone(self.s.get("x", "y"))

    def test_blank_inputs_raise(self) -> None:
        with self.assertRaises(ValueError):
            self.s.execute("", "k", lambda: None)
        with self.assertRaises(ValueError):
            self.s.execute("ns", "", lambda: None)


class TestDirectAPI(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.s = ids.IdempotencyStore(Path(self._tmp.name) / "i.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_forget_removes(self) -> None:
        self.s.execute("x", "k", lambda: "v")
        self.assertTrue(self.s.forget("x", "k"))
        self.assertFalse(self.s.seen("x", "k"))

    def test_forget_unknown_false(self) -> None:
        self.assertFalse(self.s.forget("x", "nope"))

    def test_get_returns_entry(self) -> None:
        self.s.execute("x", "k", lambda: {"a": 1})
        entry = self.s.get("x", "k")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.value, {"a": 1})
        self.assertFalse(entry.is_error)


class TestCleanup(unittest.TestCase):
    def test_cleanup_prunes_expired(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        s = ids.IdempotencyStore(Path(tmp.name) / "i.db")
        s.execute("x", "a", lambda: "v", ttl_s=0.05)
        s.execute("x", "b", lambda: "v", ttl_s=3600)
        time.sleep(0.1)
        pruned = s.cleanup()
        self.assertEqual(pruned, 1)
        self.assertFalse(s.seen("x", "a"))
        self.assertTrue(s.seen("x", "b"))
        tmp.cleanup()


class TestBytes(unittest.TestCase):
    def test_bytes_roundtrip(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        s = ids.IdempotencyStore(Path(tmp.name) / "i.db")
        blob = b"binary payload \x00\x01\x02"
        s.execute("x", "blob", lambda: blob)
        entry = s.get("x", "blob")
        self.assertEqual(entry.value, blob)
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        s = ids.IdempotencyStore(Path(tmp.name) / "i.db")
        s.execute("shopify", "a", lambda: 1)
        s.execute("shopify", "b", lambda: 2)
        s.execute("meta", "a", lambda: 3)
        stats = s.stats()
        self.assertEqual(stats["live"], 3)
        self.assertEqual(stats["by_namespace"]["shopify"], 2)
        self.assertEqual(stats["by_namespace"]["meta"], 1)
        tmp.cleanup()


class TestSingleton(unittest.TestCase):
    def test_store_returns_same_instance(self) -> None:
        self.assertIs(ids.store(), ids.store())


if __name__ == "__main__":
    unittest.main()
