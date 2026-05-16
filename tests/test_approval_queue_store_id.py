"""Tests for the per-store column on ``pending_actions`` and the
matching filters across ``enqueue`` / ``list_pending`` /
``list_by_status`` / ``DecisionRetrieval.retrieve``.

Foundation for the cross-store transfer learning surface
(forthcoming PR). Older rows enqueued before the column existed
have ``store_id=NULL`` and are excluded from filtered reads,
which preserves backward compat -- existing callers see no
change.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.approval.queue import (
    ApprovalQueue,
    ApprovalStatus,
)
from core.decision_retrieval import DecisionRetrieval


@pytest.fixture
def temp_queue(tmp_path):
    """Per-test ApprovalQueue with an isolated SQLite file."""
    db = tmp_path / "queue.db"
    return ApprovalQueue(db_path=db)


# ─── Schema migration ────────────────────────────────────────


class TestSchemaMigration:

    def test_new_db_has_store_id_column(self, temp_queue):
        cols = {
            r["name"] for r in temp_queue._conn.execute(
                "PRAGMA table_info(pending_actions)",
            ).fetchall()
        }
        assert "store_id" in cols

    def test_migration_alters_pre_existing_db(self, tmp_path):
        """A DB created with the OLD schema (no store_id column)
        gets the column added on next ApprovalQueue init."""
        db = tmp_path / "legacy.db"
        # Bootstrap a legacy DB without store_id.
        conn = sqlite3.connect(str(db))
        conn.execute("""
            CREATE TABLE pending_actions (
                id TEXT PRIMARY KEY,
                engine TEXT NOT NULL,
                action_type TEXT NOT NULL,
                capability TEXT NOT NULL,
                params_json TEXT NOT NULL,
                narrative TEXT,
                confidence REAL,
                status TEXT NOT NULL,
                proposed_at REAL NOT NULL,
                decided_at REAL,
                decided_by TEXT,
                decision_reason TEXT,
                result_json TEXT
            )
        """)
        # Insert a row that pre-dates the column.
        conn.execute(
            "INSERT INTO pending_actions "
            "(id, engine, action_type, capability, params_json, "
            " status, proposed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("legacy_1", "loyalty", "mint", "CAP", "{}",
             "executed", 1234567890.0),
        )
        conn.commit()
        conn.close()

        # Init through the queue -- should run the ALTER TABLE.
        q = ApprovalQueue(db_path=db)
        cols = {
            r["name"] for r in q._conn.execute(
                "PRAGMA table_info(pending_actions)",
            ).fetchall()
        }
        assert "store_id" in cols
        # Legacy row is queryable; store_id is None
        actions = q.list_by_status(
            ApprovalStatus.EXECUTED, engine="loyalty", limit=10,
        )
        assert len(actions) == 1
        assert actions[0].store_id is None


# ─── Enqueue + ApprovalAction shape ──────────────────────────


class TestEnqueueWithStoreId:

    def test_enqueue_persists_store_id(self, temp_queue):
        action = temp_queue.enqueue(
            engine="loyalty",
            action_type="mint_loyalty_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"customer_id": "x"},
            store_id="store-a",
        )
        assert action.store_id == "store-a"
        # Round-trip via DB read
        refreshed = temp_queue.get(action.id)
        assert refreshed.store_id == "store-a"

    def test_enqueue_without_store_id_persists_null(self, temp_queue):
        action = temp_queue.enqueue(
            engine="loyalty",
            action_type="mint_loyalty_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"customer_id": "y"},
        )
        assert action.store_id is None

    def test_to_dict_includes_store_id(self, temp_queue):
        action = temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="CAP", params={},
            store_id="store-a",
        )
        d = action.to_dict()
        assert d["store_id"] == "store-a"


# ─── list_pending + list_by_status with store_id ─────────────


class TestListFilters:

    def test_list_pending_filters_by_store(self, temp_queue):
        temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="CAP", params={}, store_id="store-a",
        )
        temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="CAP", params={}, store_id="store-b",
        )
        temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="CAP", params={},
        )  # no store_id

        # Filter to store-a only
        pending = temp_queue.list_pending(store_id="store-a")
        # Auto-approve may transition the enqueue -- check whichever
        # actions are still PENDING, only the store-a one should
        # surface here.
        for a in pending:
            assert a.store_id == "store-a"

    def test_list_by_status_filters_by_store(self, temp_queue):
        # Force into EXECUTED state via a transition path
        # (enqueue → approve → executed)
        a1 = temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="CAP", params={}, store_id="store-a",
        )
        a2 = temp_queue.enqueue(
            engine="loyalty", action_type="mint",
            capability="CAP", params={}, store_id="store-b",
        )

        # Manually flip to EXECUTED via internal API
        # (this is what the executor would do)
        with temp_queue._conn:
            temp_queue._conn.execute(
                "UPDATE pending_actions SET status = ? "
                "WHERE id IN (?, ?)",
                ("executed", a1.id, a2.id),
            )

        for_a = temp_queue.list_by_status(
            ApprovalStatus.EXECUTED, store_id="store-a", limit=10,
        )
        assert len(for_a) == 1
        assert for_a[0].store_id == "store-a"

        for_b = temp_queue.list_by_status(
            ApprovalStatus.EXECUTED, store_id="store-b", limit=10,
        )
        assert len(for_b) == 1
        assert for_b[0].store_id == "store-b"

        # No filter returns both
        all_executed = temp_queue.list_by_status(
            ApprovalStatus.EXECUTED, limit=10,
        )
        assert len(all_executed) == 2


# ─── DecisionRetrieval.retrieve with store_id ────────────────


class TestRetrievalStoreFilter:

    def test_retrieve_filters_by_store(self, temp_queue):
        for sid, n in [("store-a", 3), ("store-b", 2), (None, 1)]:
            for i in range(n):
                a = temp_queue.enqueue(
                    engine="loyalty", action_type="mint",
                    capability="CAP", params={"i": i},
                    store_id=sid,
                )
                with temp_queue._conn:
                    temp_queue._conn.execute(
                        "UPDATE pending_actions SET status=?, "
                        "decided_at=? WHERE id=?",
                        ("executed", 1000.0 + i, a.id),
                    )

        retriever = DecisionRetrieval(queue=temp_queue)
        a_results = retriever.retrieve(
            engine="loyalty", store_id="store-a", k=10,
        )
        assert len(a_results) == 3
        assert all(r["store_id"] == "store-a" for r in a_results)

        # Fleet-wide (no store_id) sees all 6 (3 + 2 + 1)
        all_results = retriever.retrieve(
            engine="loyalty", k=10,
        )
        assert len(all_results) == 6
