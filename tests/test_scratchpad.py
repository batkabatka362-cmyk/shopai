"""Scratchpad — TTL, cap, session isolation tests."""
from __future__ import annotations

import time
import unittest

from core.memory import scratchpad as sp


class TestBasic(unittest.TestCase):
    def test_write_and_read(self) -> None:
        pad = sp.Scratchpad("s1")
        pad.write("ns", "k", {"a": 1})
        self.assertEqual(pad.read("ns", "k"), {"a": 1})

    def test_read_missing_returns_none(self) -> None:
        pad = sp.Scratchpad("s")
        self.assertIsNone(pad.read("ns", "missing"))

    def test_delete(self) -> None:
        pad = sp.Scratchpad("s")
        pad.write("ns", "k", 1)
        self.assertTrue(pad.delete("ns", "k"))
        self.assertFalse(pad.delete("ns", "k"))  # idempotent


class TestTTL(unittest.TestCase):
    def test_expired_note_not_returned(self) -> None:
        pad = sp.Scratchpad("s")
        pad.write("ns", "k", 1, ttl_s=0)
        time.sleep(0.01)
        self.assertIsNone(pad.read("ns", "k"))

    def test_purge_expired(self) -> None:
        pad = sp.Scratchpad("s")
        pad.write("ns", "a", 1, ttl_s=0)
        pad.write("ns", "b", 2, ttl_s=60)
        time.sleep(0.01)
        purged = pad.purge_expired()
        self.assertEqual(purged, 1)
        self.assertIsNone(pad.read("ns", "a"))
        self.assertEqual(pad.read("ns", "b"), 2)


class TestCap(unittest.TestCase):
    def test_cap_evicts_oldest(self) -> None:
        pad = sp.Scratchpad("s")
        for i in range(5):
            pad.write("ns", f"k{i}", i, cap=3)
        # Only k2, k3, k4 should remain (oldest evicted)
        live = pad.list_namespace("ns")
        self.assertEqual(len(live), 3)
        keys = {n.key for n in live}
        self.assertEqual(keys, {"k2", "k3", "k4"})


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        sp._registry.clear()

    def test_session_idempotent_for_same_id(self) -> None:
        a = sp.session("abc")
        b = sp.session("abc")
        self.assertIs(a, b)

    def test_different_ids_are_isolated(self) -> None:
        a = sp.session("sess1")
        a.write("ns", "k", "from_A")
        b = sp.session("sess2")
        self.assertIsNone(b.read("ns", "k"))

    def test_drop_session(self) -> None:
        sp.session("sess3")
        self.assertTrue(sp.drop_session("sess3"))
        self.assertFalse(sp.drop_session("sess3"))

    def test_stats_summarises_registry(self) -> None:
        a = sp.session("sA")
        a.write("ns", "k", 1)
        b = sp.session("sB")
        b.write("ns", "k1", 1)
        b.write("ns", "k2", 2)
        s = sp.stats()
        self.assertEqual(s["session_count"], 2)
        self.assertEqual(s["total_notes"], 3)


if __name__ == "__main__":
    unittest.main()
