"""Tests for the new ``/api/approvals/*`` HTTP endpoints — sweep,
approve-all, and audit. The CLI verbs are tested separately; these
exercise the HTTP-layer plumbing (body parsing, validation, response
shape) so a future UI gets the same toolkit as the terminal.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest


def _make_handler():
    """Build a minimal handler with ``_json_response`` capturing
    the (status, body) pair instead of writing to a socket.
    """
    from api.server import ShopAIHandler

    handler = ShopAIHandler.__new__(ShopAIHandler)
    responses: list[tuple[int, dict]] = []
    handler._json_response = (
        lambda status, body: responses.append((status, body))
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


def _backdate(queue, action, age_seconds: float) -> None:
    backdated = time.time() - age_seconds
    with queue._conn:
        queue._conn.execute(
            "UPDATE pending_actions SET proposed_at = ? WHERE id = ?",
            (backdated, action.id),
        )


# ─── POST /api/approvals/sweep ────────────────────────────────────


class TestSweepEndpoint:

    def test_invalid_older_than_returns_400(self, isolated_queue):
        handler, responses = _make_handler()
        handler._approvals_sweep({"older_than": "garbage"})
        status, body = responses[0]
        assert status == 400
        assert "Invalid 'older_than'" in body["error"]

    def test_dry_run_returns_candidates(self, isolated_queue):
        a = isolated_queue.enqueue(
            engine="x", action_type="probe",
            capability="X", params={}, narrative="",
        )
        _backdate(isolated_queue, a, age_seconds=3600)

        handler, responses = _make_handler()
        handler._approvals_sweep(
            {"older_than": "1m", "dry_run": True},
        )
        status, body = responses[0]
        assert status == 200
        assert body["status"] == "dry_run"
        assert body["count"] == 1
        assert body["candidates"][0]["id"] == a.id
        # State unchanged
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(a.id).status == ApprovalStatus.PENDING

    def test_live_sweep_returns_expired_list(self, isolated_queue):
        a = isolated_queue.enqueue(
            engine="x", action_type="probe",
            capability="X", params={}, narrative="",
        )
        _backdate(isolated_queue, a, age_seconds=3600)

        handler, responses = _make_handler()
        handler._approvals_sweep({"older_than": "1m"})
        status, body = responses[0]
        assert status == 200
        assert body["status"] == "swept"
        assert body["expired_count"] == 1
        assert body["expired"][0]["id"] == a.id
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(a.id).status == ApprovalStatus.EXPIRED

    def test_no_stale_actions(self, isolated_queue):
        isolated_queue.enqueue(
            engine="x", action_type="probe",
            capability="X", params={}, narrative="",
        )
        handler, responses = _make_handler()
        handler._approvals_sweep({"older_than": "7d"})
        status, body = responses[0]
        assert status == 200
        assert body["expired_count"] == 0


# ─── POST /api/approvals/approve-all ──────────────────────────────


class TestApproveAllEndpoint:

    def test_empty_queue_returns_zero(self, isolated_queue):
        handler, responses = _make_handler()
        handler._approvals_approve_all({})
        status, body = responses[0]
        assert status == 200
        assert body["approved_count"] == 0
        assert body["status"] == "approved"

    def test_invalid_engine_type_returns_400(self, isolated_queue):
        handler, responses = _make_handler()
        handler._approvals_approve_all({"engine": ["not", "a", "string"]})
        status, body = responses[0]
        assert status == 400
        assert "'engine'" in body["error"]

    def test_invalid_min_confidence_returns_400(self, isolated_queue):
        handler, responses = _make_handler()
        handler._approvals_approve_all(
            {"min_confidence": "not_a_number"},
        )
        status, body = responses[0]
        assert status == 400
        assert "min_confidence" in body["error"]

    def test_no_filter_approves_all(self, isolated_queue):
        a = isolated_queue.enqueue(
            engine="cart_recovery", action_type="probe",
            capability="X", params={}, narrative="", confidence=0.85,
        )
        b = isolated_queue.enqueue(
            engine="loyalty", action_type="probe",
            capability="X", params={}, narrative="", confidence=0.9,
        )

        handler, responses = _make_handler()
        handler._approvals_approve_all({"by": "alice"})
        status, body = responses[0]
        assert status == 200
        assert body["approved_count"] == 2
        assert set(body["approved_ids"]) == {a.id, b.id}

        from core.approval.queue import ApprovalStatus
        for action in (a, b):
            current = isolated_queue.get(action.id)
            assert current.status == ApprovalStatus.APPROVED
            assert current.decided_by == "alice"

    def test_engine_plus_confidence_filter(self, isolated_queue):
        match = isolated_queue.enqueue(
            engine="cart_recovery", action_type="probe",
            capability="X", params={}, narrative="", confidence=0.95,
        )
        isolated_queue.enqueue(
            engine="loyalty", action_type="probe",
            capability="X", params={}, narrative="", confidence=0.95,
        )
        isolated_queue.enqueue(
            engine="cart_recovery", action_type="probe",
            capability="X", params={}, narrative="", confidence=0.7,
        )

        handler, responses = _make_handler()
        handler._approvals_approve_all(
            {"engine": "cart_recovery", "min_confidence": 0.9},
        )
        status, body = responses[0]
        assert status == 200
        assert body["approved_count"] == 1
        assert body["approved_ids"] == [match.id]

    def test_dry_run_lists_without_writing(self, isolated_queue):
        a = isolated_queue.enqueue(
            engine="x", action_type="probe",
            capability="X", params={}, narrative="", confidence=0.9,
        )
        handler, responses = _make_handler()
        handler._approvals_approve_all({"dry_run": True})
        status, body = responses[0]
        assert status == 200
        assert body["status"] == "dry_run"
        assert body["count"] == 1
        assert body["candidates"][0]["id"] == a.id
        from core.approval.queue import ApprovalStatus
        assert isolated_queue.get(a.id).status == ApprovalStatus.PENDING

    def test_missing_confidence_treated_as_zero(self, isolated_queue):
        """Action with None confidence MUST NOT slip past
        min_confidence — the gate is meaningless otherwise."""
        isolated_queue.enqueue(
            engine="x", action_type="probe",
            capability="X", params={}, narrative="", confidence=None,
        )
        handler, responses = _make_handler()
        handler._approvals_approve_all({"min_confidence": 0.5})
        status, body = responses[0]
        assert status == 200
        assert body["approved_count"] == 0


# ─── GET /api/approvals/audit ─────────────────────────────────────


class TestAuditEndpoint:

    def test_returns_audit_report_json(self):
        from core.approval.coverage_audit import (
            AuditReport, EnqueueCall,
        )
        from unittest.mock import patch

        report = AuditReport(
            enqueued=[EnqueueCall(
                action_type="mint_x",
                file_path="engines/x.py", line=10,
            )],
            registered=["mint_x"], missing=[], orphaned=[],
        )
        handler, responses = _make_handler()
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=report,
        ):
            handler._approvals_audit()
        status, body = responses[0]
        assert status == 200
        assert body["enqueue_site_count"] == 1
        assert body["registered_count"] == 1
        assert body["has_gaps"] is False
        assert body["missing"] == []
        assert body["enqueue_sites"][0]["action_type"] == "mint_x"
        assert body["enqueue_sites"][0]["line"] == 10

    def test_gaps_surface_in_response(self):
        from core.approval.coverage_audit import AuditReport
        from unittest.mock import patch

        report = AuditReport(
            enqueued=[], registered=[],
            missing=["mint_unhandled"], orphaned=[],
        )
        handler, responses = _make_handler()
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            return_value=report,
        ):
            handler._approvals_audit()
        status, body = responses[0]
        assert status == 200
        assert body["has_gaps"] is True
        assert body["missing"] == ["mint_unhandled"]

    def test_audit_failure_returns_500(self):
        from unittest.mock import patch

        handler, responses = _make_handler()
        with patch(
            "core.approval.coverage_audit.audit_coverage",
            side_effect=RuntimeError("scanner broken"),
        ):
            handler._approvals_audit()
        status, body = responses[0]
        assert status == 500
        assert "scanner broken" in body["error"]


# ─── route registration ───────────────────────────────────────────


class TestRouteRegistration:

    def test_new_routes_in_get_table(self):
        """The audit GET endpoint is listed in do_GET's route map."""
        import inspect

        from api.server import ShopAIHandler

        src = inspect.getsource(ShopAIHandler.do_GET)
        assert '"/api/approvals/audit"' in src

    def test_new_routes_in_post_table(self):
        """sweep + approve-all are listed in do_POST's route map."""
        import inspect

        from api.server import ShopAIHandler

        src = inspect.getsource(ShopAIHandler.do_POST)
        assert '"/api/approvals/sweep"' in src
        assert '"/api/approvals/approve-all"' in src
