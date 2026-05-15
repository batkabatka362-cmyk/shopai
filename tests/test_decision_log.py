"""Tests for the append-only decision audit trail.

Three layers:
  - ApprovalQueue persists a `decision_log` row on every status
    transition (approve, reject, attach_result, expire_stale).
  - `list_decisions(action_id, decided_by, limit)` reads them.
  - The CLI + API surfaces (`shopai approvals history` and
    `GET /api/approvals/history`) format the trail for operators.

This file covers the queue layer; CLI / API tests live in
test_cli_approvals_history.py and test_api_history_endpoint.py.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


@pytest.fixture
def queue(tmp_path: Path):
    from core.approval.queue import ApprovalQueue
    q = ApprovalQueue(db_path=tmp_path / "approval.db")
    yield q
    q._conn.close()


def _enqueue(q, engine="x", action_type="y"):
    return q.enqueue(
        engine=engine, action_type=action_type,
        capability="z", params={}, narrative="",
    )


class TestApproveWritesRow:

    def test_single_approval_logged(self, queue):
        a = _enqueue(queue)
        queue.approve(a.id, decided_by="alice", reason="lgtm")
        rows = queue.list_decisions(action_id=a.id)
        assert len(rows) == 1
        r = rows[0]
        assert r["decision"] == "approved"
        assert r["decided_by"] == "alice"
        assert r["reason"] == "lgtm"
        assert r["action_id"] == a.id
        assert isinstance(r["occurred_at"], float)

    def test_reject_logged(self, queue):
        a = _enqueue(queue)
        queue.reject(a.id, decided_by="bob", reason="too risky")
        rows = queue.list_decisions(action_id=a.id)
        assert len(rows) == 1
        assert rows[0]["decision"] == "rejected"
        assert rows[0]["decided_by"] == "bob"

    def test_no_op_transition_writes_nothing(self, queue):
        """Approving a PENDING twice — second call is idempotent
        (no-op), and must NOT add a phantom row."""
        a = _enqueue(queue)
        queue.approve(a.id, decided_by="alice")
        queue.approve(a.id, decided_by="bob")  # already APPROVED
        rows = queue.list_decisions(action_id=a.id)
        assert len(rows) == 1
        assert rows[0]["decided_by"] == "alice"


class TestAttachResultLogsSystem:

    def test_execute_success_logged_as_system(self, queue):
        a = _enqueue(queue)
        queue.approve(a.id, decided_by="op")
        queue.attach_result(a.id, success=True, result={"k": "v"})
        rows = queue.list_decisions(action_id=a.id)
        assert len(rows) == 2
        # Approve then execute, oldest-first
        assert rows[0]["decision"] == "approved"
        assert rows[1]["decision"] == "executed"
        assert rows[1]["decided_by"] == "system"
        assert rows[1]["reason"] is None

    def test_execute_failure_logged_with_reason(self, queue):
        a = _enqueue(queue)
        queue.approve(a.id, decided_by="op")
        queue.attach_result(a.id, success=False, result={"e": "boom"})
        rows = queue.list_decisions(action_id=a.id)
        assert rows[1]["decision"] == "failed"
        assert rows[1]["decided_by"] == "system"
        assert rows[1]["reason"] == "execution_failed"


class TestExpireStaleLogs:

    def test_expire_writes_system_row(self, queue):
        a = _enqueue(queue)
        # Force the action to look old by direct SQL — proposed_at
        # is the gating field for expire_stale
        queue._conn.execute(
            "UPDATE pending_actions SET proposed_at = ? WHERE id = ?",
            (time.time() - 9999, a.id),
        )
        queue._conn.commit()
        expired = queue.expire_stale(max_age_seconds=60)
        assert len(expired) == 1
        rows = queue.list_decisions(action_id=a.id)
        assert len(rows) == 1
        assert rows[0]["decision"] == "expired"
        assert rows[0]["decided_by"] == "system"
        assert "ttl_exceeded" in (rows[0]["reason"] or "")


class TestListDecisionsFilters:

    def test_per_action_oldest_first(self, queue):
        a = _enqueue(queue)
        queue.approve(a.id, decided_by="op")
        queue.attach_result(a.id, success=True, result={})
        rows = queue.list_decisions(action_id=a.id)
        assert rows[0]["decision"] == "approved"
        assert rows[1]["decision"] == "executed"

    def test_global_newest_first(self, queue):
        a = _enqueue(queue, engine="a")
        queue.approve(a.id, decided_by="op")
        time.sleep(0.01)
        b = _enqueue(queue, engine="b")
        queue.reject(b.id, decided_by="op")
        rows = queue.list_decisions()
        # Newest first → b before a
        assert rows[0]["action_id"] == b.id
        assert rows[1]["action_id"] == a.id

    def test_actor_filter(self, queue):
        a = _enqueue(queue)
        queue.approve(a.id, decided_by="alice")
        queue.attach_result(a.id, success=True)
        rows = queue.list_decisions(decided_by="system")
        assert len(rows) == 1
        assert rows[0]["decision"] == "executed"

        rows = queue.list_decisions(decided_by="alice")
        assert len(rows) == 1
        assert rows[0]["decision"] == "approved"

    def test_limit_cap(self, queue):
        # Generate 5 decisions across 5 actions
        for i in range(5):
            a = _enqueue(queue, engine=f"e{i}")
            queue.approve(a.id, decided_by="op")
        rows = queue.list_decisions(limit=2)
        assert len(rows) == 2

    def test_unknown_action_returns_empty(self, queue):
        assert queue.list_decisions(action_id="appr_nope") == []


class TestAuditTrailIsAppendOnly:

    def test_history_survives_status_change(self, queue):
        """The decision_log is independent of pending_actions
        column overwrites — even if `decided_by` got overwritten,
        history shows both calls."""
        a = _enqueue(queue)
        queue.approve(a.id, decided_by="alice", reason="ship it")
        queue.attach_result(a.id, success=True)
        # Underlying row's decided_by/decision_reason still reflect
        # the LAST live state (approve) — but the log has both
        rows = queue.list_decisions(action_id=a.id)
        assert [r["decision"] for r in rows] == ["approved", "executed"]
        assert rows[0]["reason"] == "ship it"
