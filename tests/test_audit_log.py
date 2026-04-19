"""Audit log tests."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.system import audit_log as al


class TestAppend(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log = al.AuditLog(Path(self._tmp.name) / "a.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_entry_has_genesis_prev(self) -> None:
        e = self.log.append("alice", "login", {"ip": "1.1.1.1"})
        self.assertEqual(e.prev_hash, "genesis")
        self.assertTrue(e.entry_hash)

    def test_chain_links(self) -> None:
        a = self.log.append("alice", "launch", {})
        b = self.log.append("bob", "kill", {})
        self.assertEqual(b.prev_hash, a.entry_hash)

    def test_blank_actor_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.log.append("", "x", {})

    def test_blank_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.log.append("alice", "", {})

    def test_seq_monotone(self) -> None:
        a = self.log.append("x", "a", {})
        b = self.log.append("x", "a", {})
        self.assertGreater(b.seq, a.seq)


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.log = al.AuditLog(Path(self._tmp.name) / "a.db")
        self.log.append("alice", "launch", {"id": 1})
        self.log.append("bob", "kill", {"id": 2})
        self.log.append("alice", "scale", {"id": 3})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_newest_first(self) -> None:
        entries = self.log.entries()
        # Newest-first
        self.assertEqual(entries[0].action, "scale")

    def test_filter_by_actor(self) -> None:
        alice_only = self.log.entries(actor="alice")
        self.assertEqual(len(alice_only), 2)

    def test_filter_by_action(self) -> None:
        kills = self.log.entries(action="kill")
        self.assertEqual(len(kills), 1)

    def test_latest(self) -> None:
        latest = self.log.latest()
        self.assertEqual(latest.action, "scale")

    def test_get_by_seq(self) -> None:
        first = self.log.entries()[-1]
        fetched = self.log.get(first.seq)
        self.assertEqual(fetched.entry_hash, first.entry_hash)


class TestVerify(unittest.TestCase):
    def test_clean_log_verifies(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        log = al.AuditLog(Path(tmp.name) / "a.db")
        for i in range(5):
            log.append("alice", "act", {"i": i})
        report = log.verify()
        self.assertTrue(report.ok)
        self.assertEqual(report.checked, 5)
        tmp.cleanup()

    def test_tampered_payload_detected(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        log = al.AuditLog(Path(tmp.name) / "a.db")
        log.append("alice", "a", {"v": 1})
        log.append("alice", "b", {"v": 2})
        # Tamper the payload directly
        conn = sqlite3.connect(str(log._db))
        conn.execute(
            "UPDATE audit SET payload_json=? WHERE seq=?",
            ('{"v": 999}', 1),
        )
        conn.commit()
        conn.close()
        report = log.verify()
        self.assertFalse(report.ok)
        self.assertEqual(report.broken_at, 1)
        tmp.cleanup()

    def test_chain_break_detected(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        log = al.AuditLog(Path(tmp.name) / "a.db")
        log.append("alice", "a", {})
        log.append("alice", "b", {})
        log.append("alice", "c", {})
        # Clobber the middle entry's prev_hash
        conn = sqlite3.connect(str(log._db))
        conn.execute(
            "UPDATE audit SET prev_hash=? WHERE seq=?",
            ("wrong_hash", 2),
        )
        conn.commit()
        conn.close()
        report = log.verify()
        self.assertFalse(report.ok)
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        log = al.AuditLog(Path(tmp.name) / "a.db")
        log.append("alice", "a", {})
        log.append("bob", "a", {})
        log.append("alice", "b", {})
        stats = log.stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["by_actor"]["alice"], 2)
        self.assertEqual(stats["by_action"]["a"], 2)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
