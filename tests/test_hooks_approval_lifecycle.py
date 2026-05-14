"""Integration tests for approval-queue → hooks dispatcher wiring.

The ApprovalQueue emits these named events at lifecycle
transitions:

  * ``approval.queued``   — on ``enqueue``
  * ``approval.approved`` — on ``approve``
  * ``approval.rejected`` — on ``reject``
  * ``approval.executed`` — on ``attach_result(success=True)``
  * ``approval.failed``   — on ``attach_result(success=False)``

These tests verify each transition fires the expected hook with
the expected payload, that idempotent no-op calls don't fire, and
that handler failures don't break the queue write.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core import hooks


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    """Turn off the hooks test-bypass so handlers actually fire
    during these integration tests. Mirrors the writeback recorder
    test pattern."""
    with patch(
        "core.hooks.dispatcher._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_hooks():
    hooks.clear()
    yield
    hooks.clear()


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _enqueue_one(queue, **overrides):
    return queue.enqueue(
        engine=overrides.get("engine", "discount_strategy"),
        action_type=overrides.get(
            "action_type", "mint_strategy_code",
        ),
        capability=overrides.get(
            "capability", "SHOPIFY_CREATE_DISCOUNT",
        ),
        params=overrides.get("params", {"percentage": 10}),
        narrative=overrides.get("narrative", "test narrative"),
        confidence=overrides.get("confidence", 0.8),
    )


# ─── approval.queued ───────────────────────────────────────────


class TestApprovalQueuedHook:

    def test_enqueue_fires_hook(self, isolated_queue):
        events = []
        hooks.register("approval.queued", lambda e: events.append(e))

        action = _enqueue_one(isolated_queue)

        assert len(events) == 1
        event = events[0]
        assert event["name"] == "approval.queued"
        assert event["data"]["action_id"] == action.id
        assert event["data"]["engine"] == "discount_strategy"
        assert event["data"]["action_type"] == "mint_strategy_code"
        assert event["data"]["capability"] == "SHOPIFY_CREATE_DISCOUNT"
        assert event["data"]["confidence"] == 0.8

    def test_wildcard_handler_also_fires(self, isolated_queue):
        events = []
        hooks.register(
            "approval.*", lambda e: events.append(e["name"]),
        )

        _enqueue_one(isolated_queue)

        assert events == ["approval.queued"]

    def test_handler_failure_doesnt_break_enqueue(self, isolated_queue):
        @hooks.register("approval.queued")
        def bad(event):
            raise RuntimeError("handler exploded")

        # Enqueue still succeeds even though the hook raised.
        action = _enqueue_one(isolated_queue)
        assert action.id.startswith("appr_")
        # Confirm persistence still happened.
        assert isolated_queue.get(action.id) is not None


# ─── approval.approved / rejected ──────────────────────────────


class TestApprovalDecisionHooks:

    def test_approve_fires_hook(self, isolated_queue):
        events = []
        hooks.register("approval.approved", lambda e: events.append(e))

        action = _enqueue_one(isolated_queue)
        isolated_queue.approve(
            action.id, decided_by="merchant", reason="ok",
        )

        assert len(events) == 1
        event = events[0]
        assert event["name"] == "approval.approved"
        assert event["data"]["action_id"] == action.id
        assert event["data"]["decided_by"] == "merchant"
        assert event["data"]["reason"] == "ok"

    def test_reject_fires_hook(self, isolated_queue):
        events = []
        hooks.register("approval.rejected", lambda e: events.append(e))

        action = _enqueue_one(isolated_queue)
        isolated_queue.reject(
            action.id, decided_by="merchant", reason="too risky",
        )

        assert len(events) == 1
        event = events[0]
        assert event["name"] == "approval.rejected"
        assert event["data"]["action_id"] == action.id
        assert event["data"]["reason"] == "too risky"

    def test_idempotent_approve_doesnt_double_fire(
        self, isolated_queue,
    ):
        events = []
        hooks.register("approval.approved", lambda e: events.append(e))

        action = _enqueue_one(isolated_queue)
        isolated_queue.approve(action.id, decided_by="m")
        # Second approve is a no-op (already approved); no extra hook.
        isolated_queue.approve(action.id, decided_by="m")

        assert len(events) == 1

    def test_unknown_action_id_doesnt_fire(self, isolated_queue):
        events = []
        hooks.register("approval.approved", lambda e: events.append(e))

        isolated_queue.approve("appr_does_not_exist")
        assert events == []


# ─── approval.executed / failed ────────────────────────────────


class TestApprovalResultHooks:

    def test_successful_attach_fires_executed(self, isolated_queue):
        events = []
        hooks.register("approval.executed", lambda e: events.append(e))

        action = _enqueue_one(isolated_queue)
        isolated_queue.approve(action.id, decided_by="m")
        isolated_queue.attach_result(
            action.id, success=True, result={"code": "PROMO10"},
        )

        assert len(events) == 1
        event = events[0]
        assert event["name"] == "approval.executed"
        assert event["data"]["action_id"] == action.id
        assert event["data"]["success"] is True
        assert event["data"]["result"] == {"code": "PROMO10"}

    def test_failed_attach_fires_failed(self, isolated_queue):
        events = []
        hooks.register("approval.failed", lambda e: events.append(e))

        action = _enqueue_one(isolated_queue)
        isolated_queue.approve(action.id, decided_by="m")
        isolated_queue.attach_result(
            action.id,
            success=False,
            result={"error": "adapter rejected"},
        )

        assert len(events) == 1
        event = events[0]
        assert event["name"] == "approval.failed"
        assert event["data"]["success"] is False

    def test_attach_on_non_approved_doesnt_fire(self, isolated_queue):
        events = []
        hooks.register(
            "approval.*", lambda e: events.append(e["name"]),
        )

        action = _enqueue_one(isolated_queue)
        # action is in PENDING — attach_result requires APPROVED.
        result = isolated_queue.attach_result(
            action.id, success=True,
        )
        assert result is None
        # Only the 'queued' hook fired (from enqueue). attach_result
        # did NOT transition so no executed/failed hook.
        assert events == ["approval.queued"]


# ─── full lifecycle round-trip ─────────────────────────────────


class TestFullLifecycle:

    def test_queue_approve_execute_fires_three_events(
        self, isolated_queue,
    ):
        events = []
        hooks.register(
            "approval.*", lambda e: events.append(e["name"]),
        )

        action = _enqueue_one(isolated_queue)
        isolated_queue.approve(action.id, decided_by="merchant")
        isolated_queue.attach_result(
            action.id, success=True, result={},
        )

        assert events == [
            "approval.queued",
            "approval.approved",
            "approval.executed",
        ]

    def test_queue_reject_fires_two_events(self, isolated_queue):
        events = []
        hooks.register(
            "approval.*", lambda e: events.append(e["name"]),
        )

        action = _enqueue_one(isolated_queue)
        isolated_queue.reject(action.id, decided_by="merchant")

        assert events == [
            "approval.queued",
            "approval.rejected",
        ]
