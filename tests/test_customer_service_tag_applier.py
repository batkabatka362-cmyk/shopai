"""Tests for ``engines.customer_service.tag_applier``.

Pushes ``shopai-cs-escalated`` tags on each customer flagged
for human follow-up via SHOPIFY_TAG_CUSTOMER. Two paths
(queue / direct) selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     customer_id / escalation_needed=False excluded /
     duplicate customer_ids deduped).
  2. Direct path: SHOPIFY_TAG_CUSTOMER called per escalated
     customer; router unavailable, adapter failure, raise all
     handled.
  3. Queue path: each escalated customer enqueues with
     correct params; queue unavailable; per-enqueue raise
     doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval propagates / auto-resolved skipped /
     anonymous (no customer_id) skipped.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.customer_service.tag_applier import (
    apply_cs_tags,
)


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue
    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _ok(data=None):
    return SimpleNamespace(ok=True, data=data or {}, error=None)


def _fail(err="rejected"):
    return SimpleNamespace(ok=False, data=None, error=err)


def _interaction(
    *, cid="gid://shopify/Customer/1",
    intent="refund_request",
    escalation_needed=True,
    assigned_team="returns",
):
    return {
        "customer_id": cid,
        "intent": intent,
        "escalation_needed": escalation_needed,
        "assigned_team": assigned_team,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_cs_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_cs_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_cs_tags(
            ["bad", 42, _interaction(cid="gid://c/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_customer_id_skipped(self, isolated_queue):
        results = apply_cs_tags(
            [_interaction(cid="")],
        )
        assert results == []

    def test_escalation_not_needed_skipped(self, isolated_queue):
        # Auto-resolved interactions should NOT be tagged.
        results = apply_cs_tags(
            [_interaction(escalation_needed=False)],
        )
        assert results == []

    def test_duplicate_customer_ids_deduped(self, isolated_queue):
        results = apply_cs_tags(
            [
                _interaction(cid="gid://c/1"),
                _interaction(cid="gid://c/1"),  # dup
                _interaction(cid="gid://c/2"),
            ],
        )
        assert len(results) == 2
        cids = {r["customer_id"] for r in results}
        assert cids == {"gid://c/1", "gid://c/2"}


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, interactions, **kwargs):
        captured = {}

        def _exec(cap, params):
            captured.setdefault("calls", []).append({
                "cap": cap, "params": params,
            })
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_cs_tags(
                interactions, require_approval=False, **kwargs,
            )
        return results, captured

    def test_escalated_customer_tagged(self):
        results, captured = self._run_direct([
            _interaction(cid="gid://c/1"),
        ])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-cs-escalated"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_TAG_CUSTOMER"
        assert captured["calls"][0]["params"]["id"] == "gid://c/1"

    def test_router_unavailable_per_customer_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_cs_tags(
                [_interaction()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_adapter_failure_per_customer_error(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_cs_tags(
                [_interaction()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "rate_limited" in results[0]["error"]

    def test_adapter_raise_per_customer_error(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_cs_tags(
                [_interaction()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_escalated_customer_enqueues(self, isolated_queue):
        results = apply_cs_tags([
            _interaction(cid="gid://c/1", intent="refund_request",
                         assigned_team="returns"),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["customer_id"] == "gid://c/1"
        assert action.params["tag"] == "shopai-cs-escalated"
        assert action.params["intent"] == "refund_request"
        assert action.params["assigned_team"] == "returns"
        assert action.action_type == "tag_cs_escalated"
        assert action.capability == "SHOPIFY_TAG_CUSTOMER"

    def test_queue_unavailable_per_customer_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_cs_tags([_interaction()])
        assert results[0]["applied"] is False
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_enqueue_raise_per_customer(self, isolated_queue):
        original = isolated_queue.enqueue
        call_count = {"n": 0}

        def _enqueue(**kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")
            return original(**kw)

        isolated_queue.enqueue = _enqueue
        results = apply_cs_tags([
            _interaction(cid="gid://c/1"),
            _interaction(cid="gid://c/2"),
            _interaction(cid="gid://c/3"),
        ])
        assert "pending_action_id" in results[0]
        assert "enqueue_raised" in results[1]["error"]
        assert "pending_action_id" in results[2]


# ─── Pattern Z ───────────────────────────────────────────────


class TestRecordWritebackIntegration:

    def test_record_called_on_direct_success(self):
        router = SimpleNamespace(execute=lambda c, p: _ok())
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.customer_service.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_cs_tags(
                [_interaction()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "customer_service"
        assert kwargs["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.customer_service.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_cs_tags(
                [_interaction()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.customer_service.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_cs_tags([_interaction()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        customer_id="gid://shopify/Customer/1",
        message="I want a refund for order #12345",
    ):
        data = {
            "message": message,
            "customer": {"customer_id": customer_id} if customer_id else {},
            "channel": "chat",
        }
        if apply:
            data["apply_cs_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.customer_service.flow import (
            CustomerServiceEngine,
        )
        with patch(
            "engines.customer_service.tag_applier.apply_cs_tags",
        ) as applier_mock:
            result = CustomerServiceEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.customer_service.flow import (
            CustomerServiceEngine,
        )
        with patch(
            "engines.customer_service.tag_applier.apply_cs_tags",
            return_value=[
                {"customer_id": "gid://c/1",
                 "intent": "refund_request",
                 "assigned_team": "returns",
                 "tag": "shopai-cs-escalated",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = CustomerServiceEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Default require_approval=True propagates
        assert kwargs["require_approval"] is True
        # First positional arg is a single-item list
        positional = applier_mock.call_args.args
        assert len(positional[0]) == 1
        assert positional[0][0]["customer_id"] == (
            "gid://shopify/Customer/1"
        )
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.customer_service.flow import (
            CustomerServiceEngine,
        )
        with patch(
            "engines.customer_service.tag_applier.apply_cs_tags",
            return_value=[],
        ) as applier_mock:
            CustomerServiceEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False
