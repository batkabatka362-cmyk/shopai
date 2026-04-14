"""Dashboard chat session persistence — Option J.

Covers the on-disk ``SessionStore`` and its four HTTP endpoints:

* ``SessionStore`` — CRUD correctness under normal use, plus the
  unhappy paths: malformed JSON on disk, concurrent save from multiple
  threads, session/turn caps, title derivation, atomic write recovery.
* ``GET /api/chat/sessions`` — returns summaries, never bodies.
* ``GET /api/chat/session?id=...`` — 400/404/200 matrix.
* ``POST /api/chat/session`` — upsert shape + id minting.
* ``DELETE /api/chat/session?id=...`` — deletion + 404 on miss.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from dashboard.app import DashboardAPIHandler
from dashboard.chat_sessions import (
    MAX_SESSIONS,
    MAX_TURNS,
    SessionStore,
    get_session_store,
    reset_session_store,
)


def _handler(path: str = "/api/chat/sessions") -> DashboardAPIHandler:
    h = object.__new__(DashboardAPIHandler)
    h._captured = []
    h._json = lambda status, data: h._captured.append((status, data))
    h.path = path
    return h


@pytest.fixture
def store(tmp_path):
    """A fresh SessionStore rooted at a throwaway directory."""
    return SessionStore(path=tmp_path / "sessions.json")


@pytest.fixture
def singleton_store(tmp_path, monkeypatch):
    """Reset the module-level singleton to point at ``tmp_path``.

    Used for endpoint tests so production and test inboxes never mix.
    """
    monkeypatch.setenv("SHOPAI_CHAT_SESSIONS_PATH",
                       str(tmp_path / "sessions.json"))
    reset_session_store()
    yield get_session_store()
    reset_session_store()


# ---------------------------------------------------------------------------
# SessionStore — CRUD
# ---------------------------------------------------------------------------


class TestSessionStoreCRUD:
    def test_empty_list_when_fresh(self, store):
        assert store.list() == []

    def test_save_mints_id(self, store):
        sid = store.save(None, [{"role": "user", "content": "hi"}])
        assert sid.startswith("sess-")
        assert len(store.list()) == 1

    def test_save_honours_supplied_id(self, store):
        sid = store.save("custom-id", [{"role": "user", "content": "x"}])
        assert sid == "custom-id"

    def test_get_roundtrips_turns(self, store):
        sid = store.save(None, [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ])
        got = store.get(sid)
        assert got is not None
        assert len(got["turns"]) == 2
        assert got["turns"][0]["role"] == "user"

    def test_get_unknown_returns_none(self, store):
        assert store.get("no-such-id") is None

    def test_update_in_place(self, store):
        sid = store.save(None, [{"role": "user", "content": "one"}])
        t1 = store.get(sid)["updated_at"]
        time.sleep(0.01)
        store.save(sid, [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ])
        got = store.get(sid)
        assert len(got["turns"]) == 2
        assert got["updated_at"] > t1

    def test_delete_returns_true_when_existed(self, store):
        sid = store.save(None, [{"role": "user", "content": "x"}])
        assert store.delete(sid) is True
        assert store.get(sid) is None

    def test_delete_returns_false_when_missing(self, store):
        assert store.delete("missing") is False

    def test_list_is_newest_first(self, store):
        a = store.save(None, [{"role": "user", "content": "a"}])
        time.sleep(0.01)
        b = store.save(None, [{"role": "user", "content": "b"}])
        ids = [s["id"] for s in store.list()]
        assert ids == [b, a]


# ---------------------------------------------------------------------------
# Derived state — titles, caps, sanitisation
# ---------------------------------------------------------------------------


class TestDerivedState:
    def test_title_derived_from_first_user_turn(self, store):
        sid = store.save(None, [
            {"role": "user", "content": "какой статус у магазина?"},
            {"role": "assistant", "content": "all green"},
        ])
        got = store.get(sid)
        assert "статус" in got["title"]

    def test_supplied_title_wins(self, store):
        sid = store.save(None,
                         [{"role": "user", "content": "x"}],
                         title="Custom title")
        assert store.get(sid)["title"] == "Custom title"

    def test_title_clamped(self, store):
        long = "y" * 500
        sid = store.save(None,
                         [{"role": "user", "content": long}])
        assert len(store.get(sid)["title"]) <= 80

    def test_turn_cap_keeps_most_recent(self, store):
        turns = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"turn {i}"}
            for i in range(MAX_TURNS + 10)
        ]
        sid = store.save(None, turns)
        got = store.get(sid)
        assert len(got["turns"]) == MAX_TURNS
        # Most-recent slice — last turn carries the highest index.
        assert got["turns"][-1]["content"].endswith(str(MAX_TURNS + 9))

    def test_session_cap_trims_oldest(self, store, monkeypatch):
        # Shrink the cap so we don't have to write 50+ sessions.
        monkeypatch.setattr("dashboard.chat_sessions.MAX_SESSIONS", 3)
        ids = []
        for i in range(5):
            ids.append(store.save(
                None, [{"role": "user", "content": f"msg {i}"}],
            ))
            time.sleep(0.005)
        surviving = {s["id"] for s in store.list()}
        # The two oldest should have been trimmed.
        assert len(surviving) == 3
        assert ids[0] not in surviving
        assert ids[1] not in surviving
        assert ids[-1] in surviving

    def test_malformed_turns_dropped(self, store):
        sid = store.save(None, [
            {"role": "user", "content": "ok"},
            "not a dict",
            {"role": "weird", "content": "wrong role"},
            {"role": "assistant"},  # missing content
            {"role": "assistant", "content": "also ok"},
        ])
        assert len(store.get(sid)["turns"]) == 2

    def test_content_clamped(self, store):
        big = "x" * 10_000
        sid = store.save(None, [{"role": "user", "content": big}])
        stored = store.get(sid)["turns"][0]["content"]
        assert len(stored) <= 4000


# ---------------------------------------------------------------------------
# Resilience
# ---------------------------------------------------------------------------


class TestResilience:
    def test_missing_file_acts_as_empty(self, tmp_path):
        s = SessionStore(path=tmp_path / "never-written.json")
        assert s.list() == []

    def test_corrupt_json_acts_as_empty(self, tmp_path):
        p = tmp_path / "broken.json"
        p.write_text("{not valid", encoding="utf-8")
        s = SessionStore(path=p)
        assert s.list() == []
        # Save should still succeed and overwrite the broken file.
        sid = s.save(None, [{"role": "user", "content": "hi"}])
        reloaded = SessionStore(path=p)
        assert reloaded.get(sid) is not None

    def test_wrong_shape_acts_as_empty(self, tmp_path):
        p = tmp_path / "wrong.json"
        p.write_text('{"sessions": "not a list"}', encoding="utf-8")
        s = SessionStore(path=p)
        assert s.list() == []

    def test_concurrent_saves_do_not_clobber(self, store):
        def _worker(i):
            store.save(None, [{"role": "user", "content": f"msg {i}"}])

        threads = [threading.Thread(target=_worker, args=(i,))
                   for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Every save should have landed — the lock must serialise RMW.
        assert len(store.list()) == 10

    def test_atomic_write_survives_crash_midway(self, store, monkeypatch):
        # First write works, then a subsequent write fails during rename.
        store.save(None, [{"role": "user", "content": "first"}])
        existing = list(store.list())
        assert len(existing) == 1

        real_replace = __import__("os").replace

        def _boom(src, dst):
            raise OSError("simulated crash")

        import os as _os
        monkeypatch.setattr(_os, "replace", _boom)

        with pytest.raises(OSError):
            store.save(None, [{"role": "user", "content": "second"}])

        # Restore + confirm the first write is still intact.
        monkeypatch.setattr(_os, "replace", real_replace)
        still = store.list()
        assert len(still) == 1
        assert still[0]["id"] == existing[0]["id"]


# ---------------------------------------------------------------------------
# Env-driven singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_env_override_redirects_storage(self, tmp_path, monkeypatch):
        target = tmp_path / "override.json"
        monkeypatch.setenv("SHOPAI_CHAT_SESSIONS_PATH", str(target))
        reset_session_store()
        try:
            s = get_session_store()
            sid = s.save(None, [{"role": "user", "content": "x"}])
            assert target.exists()
            data = json.loads(target.read_text(encoding="utf-8"))
            assert any(sess["id"] == sid for sess in data["sessions"])
        finally:
            reset_session_store()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class TestSessionsListEndpoint:
    def test_empty(self, singleton_store):
        h = _handler()
        h._api_chat_sessions_list()
        status, data = h._captured[-1]
        assert status == 200
        assert data == {"sessions": []}

    def test_populated(self, singleton_store):
        singleton_store.save(None, [{"role": "user", "content": "hi"}],
                             title="First")
        singleton_store.save(None, [{"role": "user", "content": "yo"}],
                             title="Second")
        h = _handler()
        h._api_chat_sessions_list()
        status, data = h._captured[-1]
        assert status == 200
        titles = [s["title"] for s in data["sessions"]]
        assert "First" in titles and "Second" in titles
        # Summaries only — no turn bodies leaked.
        for s in data["sessions"]:
            assert "turns" not in s
            assert "turn_count" in s


class TestSessionGetEndpoint:
    def test_requires_id(self, singleton_store):
        h = _handler(path="/api/chat/session")
        h._api_chat_session_get()
        status, data = h._captured[-1]
        assert status == 400
        assert "id" in data["error"]

    def test_404_unknown(self, singleton_store):
        h = _handler(path="/api/chat/session?id=nope")
        h._api_chat_session_get()
        status, _ = h._captured[-1]
        assert status == 404

    def test_returns_turns(self, singleton_store):
        sid = singleton_store.save(None, [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ])
        h = _handler(path=f"/api/chat/session?id={sid}")
        h._api_chat_session_get()
        status, data = h._captured[-1]
        assert status == 200
        assert data["id"] == sid
        assert len(data["turns"]) == 2


class TestSessionSaveEndpoint:
    def test_rejects_non_list_turns(self, singleton_store):
        h = _handler()
        h._handle_chat_session_save({"turns": "not a list"})
        status, data = h._captured[-1]
        assert status == 400
        assert "turns" in data["error"]

    def test_creates_new_session(self, singleton_store):
        h = _handler()
        h._handle_chat_session_save({
            "turns": [{"role": "user", "content": "hi"}],
        })
        status, data = h._captured[-1]
        assert status == 200
        assert data["status"] == "ok"
        assert data["id"].startswith("sess-")
        assert singleton_store.get(data["id"]) is not None

    def test_updates_existing_session(self, singleton_store):
        sid = singleton_store.save(
            None, [{"role": "user", "content": "one"}],
        )
        h = _handler()
        h._handle_chat_session_save({
            "id": sid,
            "turns": [
                {"role": "user", "content": "one"},
                {"role": "assistant", "content": "two"},
            ],
            "title": "Renamed",
        })
        status, data = h._captured[-1]
        assert status == 200
        assert data["id"] == sid
        got = singleton_store.get(sid)
        assert got["title"] == "Renamed"
        assert len(got["turns"]) == 2

    def test_fails_soft_on_store_error(self, singleton_store, monkeypatch):
        def _boom(*a, **kw):
            raise RuntimeError("disk full")

        monkeypatch.setattr(singleton_store, "save", _boom)
        h = _handler()
        h._handle_chat_session_save({
            "turns": [{"role": "user", "content": "hi"}],
        })
        status, data = h._captured[-1]
        # Never a 500 — always a JSON envelope with an error status.
        assert status == 200
        assert data["status"] == "error"
        assert "disk full" in data["error"]


class TestSessionDeleteEndpoint:
    def test_requires_id(self, singleton_store):
        h = _handler(path="/api/chat/session")
        h._handle_chat_session_delete()
        status, _ = h._captured[-1]
        assert status == 400

    def test_deletes_existing(self, singleton_store):
        sid = singleton_store.save(
            None, [{"role": "user", "content": "x"}],
        )
        h = _handler(path=f"/api/chat/session?id={sid}")
        h._handle_chat_session_delete()
        status, data = h._captured[-1]
        assert status == 200
        assert data["status"] == "ok"
        assert singleton_store.get(sid) is None

    def test_404_when_missing(self, singleton_store):
        h = _handler(path="/api/chat/session?id=nope")
        h._handle_chat_session_delete()
        status, _ = h._captured[-1]
        assert status == 404
