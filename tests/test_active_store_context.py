"""Tests for the thread-local active-store context
(``core.context``) and its integration with
``ApprovalQueue.enqueue``.

The autonomous loop sets the active store before each engine
iteration. Every action enqueued inside that block inherits
the store_id automatically -- no per-engine call-signature
change needed.
"""
from __future__ import annotations

import threading

import pytest

from core.approval.queue import ApprovalQueue
from core.context import (
    active_store,
    get_active_store_id,
    set_active_store_id,
)


@pytest.fixture(autouse=True)
def _clear_context():
    """Each test starts and ends with a clean context."""
    set_active_store_id(None)
    yield
    set_active_store_id(None)


@pytest.fixture
def temp_queue(tmp_path):
    return ApprovalQueue(db_path=tmp_path / "q.db")


# ─── Context manager + getter ────────────────────────────────


class TestContextBasics:

    def test_default_is_none(self):
        assert get_active_store_id() is None

    def test_active_store_sets_and_restores(self):
        assert get_active_store_id() is None
        with active_store("store-a"):
            assert get_active_store_id() == "store-a"
        assert get_active_store_id() is None

    def test_active_store_nesting(self):
        with active_store("outer"):
            assert get_active_store_id() == "outer"
            with active_store("inner"):
                assert get_active_store_id() == "inner"
            # Restored to outer
            assert get_active_store_id() == "outer"
        assert get_active_store_id() is None

    def test_active_store_with_none_explicitly_clears(self):
        with active_store("a"):
            assert get_active_store_id() == "a"
            with active_store(None):
                assert get_active_store_id() is None
            assert get_active_store_id() == "a"

    def test_thread_isolation(self):
        """The context is thread-local -- one thread's setter
        does NOT bleed into another."""
        set_active_store_id("main-thread")

        observed: list[str | None] = []

        def _worker():
            observed.append(get_active_store_id())
            set_active_store_id("worker-thread")
            observed.append(get_active_store_id())

        t = threading.Thread(target=_worker)
        t.start()
        t.join()

        # Worker started with no context (thread-local default)
        assert observed[0] is None
        # Worker's setter only affects its own thread
        assert observed[1] == "worker-thread"
        # Main thread's context unaffected by worker's setter
        assert get_active_store_id() == "main-thread"


# ─── Integration: enqueue picks up the context ───────────────


class TestEnqueueIntegration:

    def test_enqueue_picks_up_active_store(self, temp_queue):
        with active_store("store-a"):
            action = temp_queue.enqueue(
                engine="loyalty", action_type="mint",
                capability="CAP", params={},
            )
        # The context fallback kicked in
        assert action.store_id == "store-a"

    def test_explicit_store_id_wins_over_context(self, temp_queue):
        with active_store("store-a"):
            action = temp_queue.enqueue(
                engine="loyalty", action_type="mint",
                capability="CAP", params={},
                store_id="store-b",  # explicit
            )
        # Explicit value beats the context
        assert action.store_id == "store-b"

    def test_no_context_no_store_id(self, temp_queue):
        # Default behavior with no context: store_id is None
        action = temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="CAP", params={},
        )
        assert action.store_id is None

    def test_context_clears_after_block(self, temp_queue):
        with active_store("store-a"):
            a1 = temp_queue.enqueue(
                engine="loyalty", action_type="mint",
                capability="CAP", params={},
            )
        # Outside the block, no context → no tag
        a2 = temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="CAP", params={},
        )
        assert a1.store_id == "store-a"
        assert a2.store_id is None
