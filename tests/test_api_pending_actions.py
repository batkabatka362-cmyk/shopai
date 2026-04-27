"""Tests for the ``/api/pending-actions*`` endpoints in api.server.

Coverage:
  1. ``GET /api/pending-actions`` — empty + populated queue, engine
     filter, limit, malformed input.
  2. ``GET /api/pending-actions/<id>`` — fetch + 404.
  3. ``GET /api/pending-actions/stats`` — status counts.
  4. ``POST /api/pending-actions/<id>/approve`` — happy path,
     missing id, double-approve no-op.
  5. ``POST /api/pending-actions/<id>/reject`` — happy path.
  6. Action-id validation rejects path injection / SQL bait.

The handler is exercised through a real ``http.server`` instance
on a free port — the loop is the actual production code path,
not a mock.
"""
from __future__ import annotations

import json
import threading
from http.server import HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from api.server import ShopAIHandler
from core.approval import queue as approval_queue_module
from core.approval.queue import ApprovalQueue


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    """Swap the singleton for a temp-DB instance; restore after."""
    db_path = tmp_path / "approval.db"
    fresh = ApprovalQueue(db_path=db_path)
    monkeypatch.setattr(
        approval_queue_module, "_INSTANCE", fresh,
    )
    yield fresh
    fresh._conn.close()


@pytest.fixture
def server(isolated_queue):
    """Start a real ShopAI HTTP server on a free port."""
    httpd = HTTPServer(("127.0.0.1", 0), ShopAIHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    thread.join(timeout=2)


# ─── helpers ────────────────────────────────────────────────────


def _get(url: str) -> tuple[int, dict]:
    with urlopen(url) as resp:
        return resp.status, json.loads(resp.read())


def _post(url: str, body: dict) -> tuple[int, dict]:
    req = Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


# ─── GET /api/pending-actions ────────────────────────────────────


class TestListPendingEndpoint:

    def test_empty_queue_returns_count_zero(self, server: str):
        status, body = _get(f"{server}/api/pending-actions")
        assert status == 200
        assert body["count"] == 0
        assert body["actions"] == []

    def test_populated_queue_returns_actions(
        self, server: str, isolated_queue,
    ):
        a = isolated_queue.enqueue(
            engine="loyalty", action_type="mint_loyalty_code",
            capability="SHOPIFY_CREATE_DISCOUNT",
            params={"value": 10}, narrative="VIP reward",
            confidence=0.9,
        )
        status, body = _get(f"{server}/api/pending-actions")
        assert status == 200
        assert body["count"] == 1
        assert body["actions"][0]["id"] == a.id
        assert body["actions"][0]["narrative"] == "VIP reward"
        assert body["actions"][0]["confidence"] == 0.9

    def test_engine_filter_query_param(
        self, server: str, isolated_queue,
    ):
        loyalty = isolated_queue.enqueue(
            engine="loyalty", action_type="x", capability="X",
            params={},
        )
        isolated_queue.enqueue(
            engine="discount_strategy", action_type="x",
            capability="X", params={},
        )
        status, body = _get(
            f"{server}/api/pending-actions?engine=loyalty",
        )
        assert status == 200
        assert body["count"] == 1
        assert body["actions"][0]["id"] == loyalty.id

    def test_limit_query_param(self, server: str, isolated_queue):
        for _ in range(5):
            isolated_queue.enqueue(
                engine="x", action_type="y", capability="Z",
                params={},
            )
        status, body = _get(f"{server}/api/pending-actions?limit=2")
        assert status == 200
        assert body["count"] == 2

    def test_malformed_engine_filter_rejected(self, server: str):
        from urllib.error import HTTPError

        with pytest.raises(HTTPError) as ei:
            _get(f"{server}/api/pending-actions?engine=../etc/passwd")
        assert ei.value.code == 400


# ─── GET /api/pending-actions/<id> ───────────────────────────────


class TestGetSingleEndpoint:

    def test_fetch_existing_action(self, server: str, isolated_queue):
        a = isolated_queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={}, narrative="hi",
        )
        status, body = _get(f"{server}/api/pending-actions/{a.id}")
        assert status == 200
        assert body["id"] == a.id
        assert body["narrative"] == "hi"

    def test_fetch_unknown_id_returns_404(self, server: str):
        from urllib.error import HTTPError

        with pytest.raises(HTTPError) as ei:
            _get(f"{server}/api/pending-actions/appr_does_not_exist_123")
        assert ei.value.code == 404


# ─── stats ───────────────────────────────────────────────────────


class TestStatsEndpoint:

    def test_stats_returns_counts(self, server: str, isolated_queue):
        a = isolated_queue.enqueue(
            engine="x", action_type="y", capability="Z",
            params={},
        )
        isolated_queue.enqueue(
            engine="x", action_type="y", capability="Z",
            params={},
        )
        isolated_queue.approve(a.id)
        status, body = _get(f"{server}/api/pending-actions/stats")
        assert status == 200
        assert body["pending"] == 1
        assert body["approved"] == 1


# ─── POST /api/pending-actions/<id>/approve ──────────────────────


class TestApproveEndpoint:

    def test_approve_happy_path(self, server: str, isolated_queue):
        a = isolated_queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        status, body = _post(
            f"{server}/api/pending-actions/{a.id}/approve",
            {"by": "alice", "reason": "VIP customer"},
        )
        assert status == 200
        assert body["status"] == "approved"
        assert body["action"]["status"] == "approved"
        assert body["action"]["decided_by"] == "alice"
        assert body["action"]["decision_reason"] == "VIP customer"

    def test_double_approve_returns_noop(self, server: str, isolated_queue):
        a = isolated_queue.enqueue(
            engine="loyalty", action_type="mint", capability="X",
            params={},
        )
        _post(
            f"{server}/api/pending-actions/{a.id}/approve",
            {"by": "alice"},
        )
        status, body = _post(
            f"{server}/api/pending-actions/{a.id}/approve",
            {"by": "bob"},
        )
        assert status == 200
        assert body["status"] == "noop"
        # Original approver wins.
        assert body["action"]["decided_by"] == "alice"

    def test_approve_unknown_id_returns_404(self, server: str):
        from urllib.error import HTTPError

        with pytest.raises(HTTPError) as ei:
            _post(
                f"{server}/api/pending-actions/appr_unknown_id_123/approve",
                {},
            )
        assert ei.value.code == 404


# ─── POST /api/pending-actions/<id>/reject ───────────────────────


class TestRejectEndpoint:

    def test_reject_happy_path(self, server: str, isolated_queue):
        a = isolated_queue.enqueue(
            engine="discount_strategy", action_type="mint",
            capability="X", params={},
        )
        status, body = _post(
            f"{server}/api/pending-actions/{a.id}/reject",
            {"by": "bob", "reason": "cannibalization risk"},
        )
        assert status == 200
        assert body["status"] == "rejected"
        assert body["action"]["status"] == "rejected"
        assert body["action"]["decision_reason"] == "cannibalization risk"


# ─── action-id validation ────────────────────────────────────────


class TestActionIdValidation:

    @pytest.mark.parametrize("bad_id", [
        "../etc/passwd",
        "appr_'; DROP TABLE pending_actions; --",
        "short",
        "appr_with spaces",
        "appr_with/slash",
    ])
    def test_malformed_action_id_rejected(self, server: str, bad_id: str):
        from urllib.error import HTTPError
        from urllib.parse import quote

        # urllib needs the id URL-encoded so the path separator
        # is preserved even when the id contains slashes; the
        # server should still reject.
        encoded = quote(bad_id, safe="")
        with pytest.raises(HTTPError) as ei:
            _post(
                f"{server}/api/pending-actions/{encoded}/approve",
                {},
            )
        assert ei.value.code in (400, 404)
