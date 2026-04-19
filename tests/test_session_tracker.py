"""Session tracker tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import session_tracker as st


class TestAppend(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.s = st.SessionTracker(
            Path(self._tmp.name) / "s.db", session_gap_s=60,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_event_starts_session(self) -> None:
        sid = self.s.append("alice", st.Event(kind="visit"))
        self.assertTrue(sid)
        sess = self.s.session("alice")
        self.assertEqual(sess.event_count, 1)

    def test_blank_actor_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.s.append("", st.Event(kind="x"))

    def test_accepts_dict_event(self) -> None:
        sid = self.s.append("bob", {"kind": "click"})
        self.assertTrue(sid)


class TestStitching(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.s = st.SessionTracker(
            Path(self._tmp.name) / "s.db", session_gap_s=60,
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_events_close_in_time_join_one_session(self) -> None:
        now = time.time()
        sid1 = self.s.append("alice",
                              st.Event(kind="visit", ts=now))
        sid2 = self.s.append("alice",
                              st.Event(kind="click", ts=now + 10))
        self.assertEqual(sid1, sid2)
        sess = self.s.session("alice")
        self.assertEqual(sess.event_count, 2)

    def test_gap_spawns_new_session(self) -> None:
        now = time.time()
        sid1 = self.s.append("alice",
                              st.Event(kind="visit", ts=now))
        sid2 = self.s.append("alice",
                              st.Event(kind="visit", ts=now + 3600))
        self.assertNotEqual(sid1, sid2)

    def test_multiple_actors_isolated(self) -> None:
        now = time.time()
        a = self.s.append("alice",
                           st.Event(kind="x", ts=now))
        b = self.s.append("bob",
                           st.Event(kind="x", ts=now))
        self.assertNotEqual(a, b)


class TestReadback(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.s = st.SessionTracker(
            Path(self._tmp.name) / "s.db",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sessions_returns_newest_first(self) -> None:
        now = time.time()
        self.s.append("alice",
                       st.Event(kind="x", ts=now - 7200))
        time.sleep(0.01)
        self.s.append("alice",
                       st.Event(kind="x", ts=now - 1))
        sessions = self.s.sessions("alice")
        self.assertEqual(len(sessions), 2)
        self.assertGreaterEqual(
            sessions[0].last_seen_at, sessions[1].last_seen_at,
        )

    def test_events_loaded_in_order(self) -> None:
        now = time.time()
        for i in range(5):
            self.s.append("alice",
                           st.Event(kind=f"ev{i}", ts=now + i))
        sess = self.s.session("alice")
        kinds = [e.kind for e in sess.events]
        self.assertEqual(kinds, ["ev0", "ev1", "ev2", "ev3", "ev4"])


class TestClose(unittest.TestCase):
    def test_close_stale_by_age(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        s = st.SessionTracker(
            Path(tmp.name) / "s.db", session_gap_s=60,
        )
        now = time.time()
        s.append("alice",
                  st.Event(kind="x", ts=now - 7200))
        s.append("bob",
                  st.Event(kind="x", ts=now))
        closed = s.close_stale(gap_s=3600)
        self.assertEqual(closed, 1)
        tmp.cleanup()

    def test_close_session_by_id(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        s = st.SessionTracker(Path(tmp.name) / "s.db")
        sid = s.append("alice", st.Event(kind="x"))
        self.assertTrue(s.close_session(sid))
        sess = s.get(sid)
        self.assertTrue(sess.closed)
        tmp.cleanup()

    def test_closed_session_new_event_starts_fresh(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        s = st.SessionTracker(Path(tmp.name) / "s.db")
        sid1 = s.append("alice", st.Event(kind="x"))
        s.close_session(sid1)
        sid2 = s.append("alice", st.Event(kind="y"))
        self.assertNotEqual(sid1, sid2)
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_aggregates(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        s = st.SessionTracker(Path(tmp.name) / "s.db")
        now = time.time()
        for i in range(3):
            s.append("alice", st.Event(kind="x", ts=now + i))
        stats = s.stats()
        self.assertEqual(stats["total_sessions"], 1)
        self.assertEqual(stats["total_events"], 3)
        tmp.cleanup()


class TestEventMeta(unittest.TestCase):
    def test_meta_roundtrips(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        s = st.SessionTracker(Path(tmp.name) / "s.db")
        s.append(
            "alice",
            st.Event(kind="purchase",
                      meta={"value": 29.99, "currency": "USD"}),
        )
        sess = s.session("alice")
        self.assertEqual(
            sess.events[0].meta.get("currency"), "USD",
        )
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
