"""Tests for ``POST /api/pending-actions/<id>/execute``.

Exercises the executor through a real ``http.server`` instance —
production path, not a mock. Verifies:

  1. Approved action → 200 with status=executed.
  2. Failed dispatcher → 200 with status=failed (the HTTP call
     succeeds even when the underlying execution fails — that's
     the right shape for the merchant page).
  3. Pending action → 200 noop (execute requires approved).
  4. Already-executed action → 200 noop.
  5. Unknown id → 404.
  6. Action-id validation rejects path injection.
"""
from __future__ import annotations

import json
import threading
from http.server import HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from api.server import ShopAIHandler
from core.approval import queue as approval_queue_module
from core.approval.queue import ApprovalQueue


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(approval_queue_module, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


@pytest.fixture
def server(isolated_queue):
    httpd = HTTPServer(("127.0.0.1", 0), ShopAIHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    thread.join(timeout=2)


def _post(url: str, body: dict) -> tuple[int, dict]:
    req = Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read())


# ─── execute endpoint ──────────────────────────────────────────


class TestExecuteEndpoint:

    def test_approved_action_executes_and_flips_to_executed(
        self, server, isolated_queue,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["a"]},
        )
        isolated_queue.approve(action.id, decided_by="op")

        with patch_router_call(success=True, result={"id": "p1"}):
            status, body = _post(
                f"{server}/api/pending-actions/{action.id}/execute", {},
            )

        assert status == 200
        assert body["status"] == "executed"
        assert body["action"]["id"] == action.id
        assert body["action"]["status"] == "executed"
        assert body["action"]["result"] == {"id": "p1"}

    def test_dispatcher_failure_returns_200_with_failed_status(
        self, server, isolated_queue,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["a"]},
        )
        isolated_queue.approve(action.id)

        with patch_router_call(success=False, result={"error": "scope_missing"}):
            status, body = _post(
                f"{server}/api/pending-actions/{action.id}/execute", {},
            )

        # HTTP success — the merchant page can render the failure
        # narrative. The action's own status is FAILED.
        assert status == 200
        assert body["status"] == "failed"
        assert body["action"]["status"] == "failed"
        assert body["action"]["result"] == {"error": "scope_missing"}

    def test_pending_action_returns_noop(self, server, isolated_queue):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["a"]},
        )

        status, body = _post(
            f"{server}/api/pending-actions/{action.id}/execute", {},
        )
        assert status == 200
        assert body["status"] == "noop"
        assert "pending" in body["reason"]

    def test_already_executed_returns_noop(
        self, server, isolated_queue,
    ):
        action = isolated_queue.enqueue(
            engine="catalog",
            action_type="catalog_apply_tags",
            capability="SHOPIFY_ADD_TAGS",
            params={"product_id": "p1", "tags": ["a"]},
        )
        isolated_queue.approve(action.id)

        with patch_router_call(success=True, result={}):
            _post(f"{server}/api/pending-actions/{action.id}/execute", {})

        # Second execute → noop.
        status, body = _post(
            f"{server}/api/pending-actions/{action.id}/execute", {},
        )
        assert status == 200
        assert body["status"] == "noop"
        assert "executed" in body["reason"]

    def test_unknown_id_returns_404(self, server):
        with pytest.raises(HTTPError) as ei:
            _post(
                f"{server}/api/pending-actions/appr_unknown_id_123/execute",
                {},
            )
        assert ei.value.code == 404

    def test_path_injection_rejected(self, server):
        from urllib.parse import quote

        bad = quote("../etc/passwd", safe="")
        with pytest.raises(HTTPError) as ei:
            _post(
                f"{server}/api/pending-actions/{bad}/execute", {},
            )
        assert ei.value.code in (400, 404)


# ─── helper ────────────────────────────────────────────────────


def patch_router_call(success: bool, result: dict):
    """Convenience: patch the dispatchers' router-call helper."""
    from unittest.mock import patch
    return patch(
        "core.approval.dispatchers._router_call",
        return_value=(success, result),
    )
