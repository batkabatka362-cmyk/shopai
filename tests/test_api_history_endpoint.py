"""Tests for ``GET /api/approvals/history`` — decision audit
trail HTTP endpoint.

HTTP parity for ``shopai approvals history``. Two modes selected
by the presence of ``action_id`` query param:
  - scoped: chronological lifecycle of one action (oldest first)
  - global: newest first ticker, optionally filtered by actor
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def _make_handler(query: str = ""):
    from api.server import ShopAIHandler
    handler = ShopAIHandler.__new__(ShopAIHandler)
    handler.path = f"/api/approvals/history{query}"
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda s, b: responses.append((s, b))
    )
    return handler, responses


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _seed(queue, *, decided_by="alice", reason="ok"):
    a = queue.enqueue(
        engine="x", action_type="y", capability="z",
        params={}, narrative="",
    )
    queue.approve(a.id, decided_by=decided_by, reason=reason)
    queue.attach_result(a.id, success=True, result={"k": "v"})
    return a


class TestEmpty:

    def test_empty_global_returns_envelope(self, isolated_queue):
        handler, responses = _make_handler()
        handler._approvals_history()
        status, body = responses[0]
        assert status == 200
        assert body == {
            "decisions": [], "count": 0, "action_id": None,
        }


class TestScopedToAction:

    def test_action_lifecycle_oldest_first(self, isolated_queue):
        a = _seed(isolated_queue)
        handler, responses = _make_handler(f"?action_id={a.id}")
        handler._approvals_history()
        status, body = responses[0]
        assert status == 200
        assert body["count"] == 2
        assert body["action_id"] == a.id
        # Oldest first when scoped
        decisions = [r["decision"] for r in body["decisions"]]
        assert decisions == ["approved", "executed"]

    def test_unknown_action_returns_empty(self, isolated_queue):
        handler, responses = _make_handler(
            "?action_id=appr_does_not_exist",
        )
        handler._approvals_history()
        body = responses[0][1]
        assert body["count"] == 0
        assert body["decisions"] == []
        assert body["action_id"] == "appr_does_not_exist"


class TestGlobalFeed:

    def test_newest_first_globally(self, isolated_queue):
        _seed(isolated_queue)
        _seed(isolated_queue)
        handler, responses = _make_handler()
        handler._approvals_history()
        body = responses[0][1]
        # 2 actions × 2 transitions = 4 rows
        assert body["count"] == 4
        assert body["action_id"] is None
        # First row is the most recent transition (executed of #2)
        timestamps = [r["occurred_at"] for r in body["decisions"]]
        assert timestamps == sorted(timestamps, reverse=True)


class TestQueryParams:

    def test_decided_by_filter(self, isolated_queue):
        _seed(isolated_queue, decided_by="alice")
        _seed(isolated_queue, decided_by="bob")
        handler, responses = _make_handler("?decided_by=alice")
        handler._approvals_history()
        body = responses[0][1]
        # Only alice's approve rows (executes are by "system")
        assert body["count"] == 1
        assert body["decisions"][0]["decided_by"] == "alice"

    def test_default_limit_50(self, isolated_queue):
        # Generate 30 distinct actions
        for _ in range(30):
            _seed(isolated_queue)
        handler, responses = _make_handler()
        handler._approvals_history()
        body = responses[0][1]
        # 30 actions × 2 transitions = 60 rows; default limit 50
        assert body["count"] == 50

    def test_limit_clamped_above(self, isolated_queue):
        handler, responses = _make_handler("?limit=9999")
        handler._approvals_history()
        assert responses[0][0] == 200

    def test_limit_clamped_below(self, isolated_queue):
        handler, responses = _make_handler("?limit=0")
        handler._approvals_history()
        assert responses[0][0] == 200

    def test_limit_invalid_falls_to_default(self, isolated_queue):
        handler, responses = _make_handler("?limit=garbage")
        handler._approvals_history()
        assert responses[0][0] == 200


class TestResilience:

    def test_queue_failure_returns_empty_200(self, isolated_queue):
        with patch.object(
            isolated_queue, "list_decisions",
            side_effect=RuntimeError("db lock"),
        ):
            handler, responses = _make_handler()
            handler._approvals_history()
        status, body = responses[0]
        assert status == 200
        assert body["count"] == 0
        assert body["decisions"] == []


class TestRouteRegistration:

    def test_route_in_get_table(self):
        import inspect
        from api.server import ShopAIHandler

        src = inspect.getsource(ShopAIHandler.do_GET)
        assert '"/api/approvals/history"' in src
        assert "_approvals_history" in src
