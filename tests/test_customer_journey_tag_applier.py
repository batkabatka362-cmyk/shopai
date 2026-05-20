"""Tests for ``engines.customer_journey.tag_applier``.

Pushes ``shopai-journey-{stage}`` tags on each customer
journey via SHOPIFY_TAG_CUSTOMER. Two paths (queue / direct)
selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     customer_id / invalid stage).
  2. Direct path: SHOPIFY_TAG_CUSTOMER called per journey;
     all 4 valid stages tagged correctly; router unavailable,
     adapter failure, raise all handled.
  3. Queue path: each journey enqueues with correct params;
     queue unavailable; per-enqueue raise doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval propagates.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.customer_journey.tag_applier import (
    apply_journey_tags,
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


def _journey(*, cid="gid://shopify/Customer/1", stage="purchase"):
    return {
        "customer_id": cid,
        "furthest_stage": stage,
        "stages_visited": [stage],
        "total_events": 5,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_journey_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_journey_tags(None) == []  # type: ignore

    def test_invalid_stage_skipped(self, isolated_queue):
        # "unknown" isn't in _VALID_STAGES
        results = apply_journey_tags(
            [_journey(stage="unknown_stage")],
        )
        assert results == []

    def test_missing_customer_id_skipped(self, isolated_queue):
        results = apply_journey_tags(
            [_journey(cid="", stage="purchase")],
        )
        assert results == []

    def test_non_dict_journey_skipped(self, isolated_queue):
        results = apply_journey_tags(
            ["not a dict", 42, _journey(stage="retention")],  # type: ignore
        )
        # Only the valid retention journey goes through
        assert len(results) == 1


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, journeys):
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
            results = apply_journey_tags(
                journeys, require_approval=False,
            )
        return results, captured

    def test_each_stage_gets_correct_tag(self):
        results, captured = self._run_direct([
            _journey(cid="gid://c/1", stage="awareness"),
            _journey(cid="gid://c/2", stage="consideration"),
            _journey(cid="gid://c/3", stage="purchase"),
            _journey(cid="gid://c/4", stage="retention"),
        ])
        assert all(r["applied"] for r in results)
        tags = [r["tag"] for r in results]
        assert tags == [
            "shopai-journey-awareness",
            "shopai-journey-consideration",
            "shopai-journey-purchase",
            "shopai-journey-retention",
        ]
        # All 4 SHOPIFY_TAG_CUSTOMER calls fired
        assert len(captured["calls"]) == 4
        assert captured["calls"][0]["cap"].name == "SHOPIFY_TAG_CUSTOMER"

    def test_router_unavailable_per_customer_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_journey_tags(
                [_journey()], require_approval=False,
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
            results = apply_journey_tags(
                [_journey()], require_approval=False,
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
            results = apply_journey_tags(
                [_journey()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]

    def test_batch_continues_through_failure(self):
        call_count = {"n": 0}

        def _exec(c, p):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("transient")
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_journey_tags(
                [
                    _journey(cid="gid://c/1"),
                    _journey(cid="gid://c/2"),
                    _journey(cid="gid://c/3"),
                ],
                require_approval=False,
            )
        assert len(results) == 3
        assert results[0]["applied"] is True
        assert results[1]["applied"] is False
        assert results[2]["applied"] is True


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_each_journey_enqueues(self, isolated_queue):
        results = apply_journey_tags([
            _journey(cid="gid://c/1", stage="awareness"),
            _journey(cid="gid://c/2", stage="retention"),
        ])
        assert len(results) == 2
        assert all("pending_action_id" in r for r in results)
        assert all(r["applied"] is False for r in results)
        # Stage propagates into params
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["furthest_stage"] == "awareness"

    def test_queue_unavailable_per_customer_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_journey_tags([_journey()])
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
        results = apply_journey_tags([
            _journey(cid="gid://c/1"),
            _journey(cid="gid://c/2"),
            _journey(cid="gid://c/3"),
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
            "engines.customer_journey.tag_applier.record_writeback",
        ) as record_mock:
            apply_journey_tags(
                [_journey()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "customer_journey"
        assert kwargs["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kwargs["success"] is True

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.customer_journey.tag_applier.record_writeback",
        ) as record_mock:
            apply_journey_tags([_journey()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(self, *, apply=False, require_approval=None):
        data = {
            "customers": [
                {"id": "gid://shopify/Customer/1"},
            ],
            "events": [
                {"customer_id": "gid://shopify/Customer/1",
                 "type": "order_complete"},
            ],
            "touchpoints": [],
            "conversions": [],
        }
        if apply:
            data["apply_journey_tags"] = True
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
        from engines.customer_journey.flow import (
            CustomerJourneyEngine,
        )
        with patch(
            "engines.customer_journey.tag_applier.apply_journey_tags",
        ) as applier_mock:
            result = CustomerJourneyEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.customer_journey.flow import (
            CustomerJourneyEngine,
        )
        with patch(
            "engines.customer_journey.tag_applier.apply_journey_tags",
            return_value=[
                {"customer_id": "gid://c/1",
                 "furthest_stage": "purchase",
                 "tag": "shopai-journey-purchase",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = CustomerJourneyEngine().run(self._input(apply=True))
        applier_mock.assert_called_once()
        # Default require_approval=True propagates
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is True
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.customer_journey.flow import (
            CustomerJourneyEngine,
        )
        with patch(
            "engines.customer_journey.tag_applier.apply_journey_tags",
            return_value=[],
        ) as applier_mock:
            CustomerJourneyEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False
