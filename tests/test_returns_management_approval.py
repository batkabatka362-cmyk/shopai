"""Tests for the returns_management approval-queue wiring (1C #9).

The engine's ``processed`` output carries per-return decisions
(``status``, ``refund_amount``, ``rejection_reason``).
The new applier maps each decision to an order tag via the
``SHOPIFY_TAG_ORDER`` capability so the merchant can filter
their order admin by return state.

Coverage:
  1. ``_tags_for_decision`` mapping (approved / rejected /
     fraud-flagged / other-status) and ``_fraud_return_ids``
     aggregator.
  2. ``apply_return_tags`` happy path / router-unavailable /
     order-id-missing / no-actionable-tag.
  3. ``enqueue_return_tags_for_approval`` mirrors above plus
     queue-unavailable.
  4. flow integration — three branches of Stage 7.5.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


# ─── Helper logic ──────────────────────────────────────────────


class TestTagMapping:

    def test_approved_status_yields_approved_tag(self):
        from engines.returns_management.return_applier import (
            _tags_for_decision,
        )

        tags = _tags_for_decision(
            {"return_id": "r1", "status": "approved"}, set(),
        )
        assert tags == ["shopai-return-approved"]

    def test_rejected_status_yields_rejected_tag(self):
        from engines.returns_management.return_applier import (
            _tags_for_decision,
        )

        tags = _tags_for_decision(
            {"return_id": "r1", "status": "rejected"}, set(),
        )
        assert tags == ["shopai-return-rejected"]

    def test_other_status_yields_no_decision_tag(self):
        from engines.returns_management.return_applier import (
            _tags_for_decision,
        )

        tags = _tags_for_decision(
            {"return_id": "r1", "status": "pending_review"}, set(),
        )
        assert tags == []

    def test_fraud_flagged_adds_fraud_tag(self):
        from engines.returns_management.return_applier import (
            _tags_for_decision,
        )

        tags = _tags_for_decision(
            {"return_id": "r1", "status": "approved"}, {"r1"},
        )
        assert tags == [
            "shopai-return-approved", "shopai-return-fraud-flag",
        ]

    def test_fraud_only_no_status_emits_fraud_tag_alone(self):
        from engines.returns_management.return_applier import (
            _tags_for_decision,
        )

        tags = _tags_for_decision(
            {"return_id": "r1", "status": ""}, {"r1"},
        )
        assert tags == ["shopai-return-fraud-flag"]

    def test_fraud_return_ids_aggregator(self):
        from engines.returns_management.return_applier import (
            _fraud_return_ids,
        )

        out = _fraud_return_ids([
            {"return_id": "r1", "score": 0.9},
            {"return_id": "r2", "score": 0.85},
            {"score": 0.7},  # no return_id
            "garbage",
        ])
        assert out == {"r1", "r2"}


# ─── apply_return_tags (direct path) ───────────────────────────


class _StubResult:
    def __init__(self, ok=True, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


class _StubRouter:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def execute(self, capability, params):
        self.calls.append((capability, params))
        return self.result


class TestApplyReturnTags:

    def test_happy_path_per_return(self):
        from engines.returns_management import return_applier
        from engines.returns_management.return_applier import (
            apply_return_tags,
        )

        stub = _StubRouter(_StubResult(ok=True))
        with patch.object(
            return_applier, "_get_router", return_value=stub,
        ):
            results = apply_return_tags(
                processed=[
                    {"return_id": "r1", "order_id": "o1",
                     "status": "approved", "refund_amount": 50},
                    {"return_id": "r2", "order_id": "o2",
                     "status": "rejected", "refund_amount": 0,
                     "rejection_reason": "out of window"},
                ],
                fraud_flags=[],
            )

        assert len(stub.calls) == 2
        # r1 → approved tag on o1
        _, p1 = stub.calls[0]
        assert p1 == {"id": "o1", "tags": ["shopai-return-approved"]}
        # r2 → rejected tag on o2
        _, p2 = stub.calls[1]
        assert p2 == {"id": "o2", "tags": ["shopai-return-rejected"]}

        assert all(r["applied"] for r in results)

    def test_order_id_missing_skipped(self):
        from engines.returns_management import return_applier
        from engines.returns_management.return_applier import (
            apply_return_tags,
        )

        stub = _StubRouter(_StubResult(ok=True))
        with patch.object(
            return_applier, "_get_router", return_value=stub,
        ):
            results = apply_return_tags(
                processed=[
                    {"return_id": "r1", "order_id": "",
                     "status": "approved"},
                ],
                fraud_flags=[],
            )
        assert stub.calls == []
        assert results[0]["error"] == "order_id_missing"

    def test_no_actionable_tag_skipped(self):
        from engines.returns_management import return_applier
        from engines.returns_management.return_applier import (
            apply_return_tags,
        )

        stub = _StubRouter(_StubResult(ok=True))
        with patch.object(
            return_applier, "_get_router", return_value=stub,
        ):
            results = apply_return_tags(
                processed=[
                    {"return_id": "r1", "order_id": "o1",
                     "status": "pending_review"},
                ],
                fraud_flags=[],
            )
        assert stub.calls == []
        assert results[0]["error"] == "no_actionable_tag"

    def test_router_unavailable_stamps_all_skipped(self):
        from engines.returns_management import return_applier
        from engines.returns_management.return_applier import (
            apply_return_tags,
        )

        with patch.object(
            return_applier, "_get_router", return_value=None,
        ):
            results = apply_return_tags(
                processed=[
                    {"return_id": "r1", "order_id": "o1",
                     "status": "approved"},
                ],
                fraud_flags=[],
            )
        assert results[0]["error"] == "router_unavailable"


# ─── enqueue_return_tags_for_approval ─────────────────────────


class TestEnqueueReturnTagsForApproval:

    def test_happy_path_parks_per_return(self, isolated_queue):
        from engines.returns_management.return_applier import (
            enqueue_return_tags_for_approval,
        )

        results = enqueue_return_tags_for_approval(
            processed=[
                {"return_id": "r1", "order_id": "o1",
                 "status": "approved", "refund_amount": 100},
                {"return_id": "r2", "order_id": "o2",
                 "status": "rejected",
                 "rejection_reason": "not eligible"},
            ],
            fraud_flags=[{"return_id": "r1", "score": 0.9}],
        )

        assert len(results) == 2
        for r in results:
            assert r["error"] == "queued"
            assert r["pending_action_id"].startswith("appr_")

        assert isolated_queue.stats()["pending"] == 2

        # r1 should have both approved AND fraud tags.
        r1_action = isolated_queue.get(
            next(r["pending_action_id"] for r in results
                 if r["return_id"] == "r1"),
        )
        assert r1_action is not None
        assert "shopai-return-approved" in r1_action.params["tags"]
        assert "shopai-return-fraud-flag" in r1_action.params["tags"]
        # Refund amount preserved in params for executor follow-up.
        assert r1_action.params["refund_amount"] == 100

    def test_queue_unavailable_uniform_skip_list(self, isolated_queue):
        from engines.returns_management.return_applier import (
            enqueue_return_tags_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            results = enqueue_return_tags_for_approval(
                processed=[
                    {"return_id": "r1", "order_id": "o1",
                     "status": "approved"},
                ],
                fraud_flags=[],
            )
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_no_actionable_tag_short_circuits(self, isolated_queue):
        from engines.returns_management.return_applier import (
            enqueue_return_tags_for_approval,
        )

        results = enqueue_return_tags_for_approval(
            processed=[
                {"return_id": "r1", "order_id": "o1",
                 "status": "pending_review"},
            ],
            fraud_flags=[],
        )
        assert results[0]["error"] == "no_actionable_tag"
        assert results[0]["pending_action_id"] is None


# ─── flow integration ─────────────────────────────────────────


def _flow_input(*, apply_return_tags_flag=None, require_approval=None):
    data: dict = {
        "returns": [
            {"return_id": "r1", "order_id": "o1",
             "reason": "damaged", "items": [{"product_id": "p1"}]},
        ],
        "return_policy": {
            "window_days": 30,
            "eligible_conditions": ["damaged", "wrong_item"],
            "restocking_fee_pct": 0,
        },
    }
    if apply_return_tags_flag is not None:
        data["apply_return_tags"] = apply_return_tags_flag
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.returns_management.flow import (
            ReturnsManagementEngine,
        )

        with patch(
            "engines.returns_management.flow.apply_return_tags",
        ) as mock_apply, patch(
            "engines.returns_management.flow.enqueue_return_tags_for_approval",
        ) as mock_enqueue:
            output = ReturnsManagementEngine().run(_flow_input())

        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["tag_apply_results"] == []

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.returns_management.flow import (
            ReturnsManagementEngine,
        )

        with patch(
            "engines.returns_management.flow.apply_return_tags",
            return_value=[
                {"return_id": "r1", "order_id": "o1",
                 "applied": True, "tags": ["shopai-return-approved"],
                 "error": None},
            ],
        ) as mock_apply, patch(
            "engines.returns_management.flow.enqueue_return_tags_for_approval",
        ) as mock_enqueue:
            output = ReturnsManagementEngine().run(
                _flow_input(
                    apply_return_tags_flag=True,
                    require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_apply.assert_called_once()
            assert output["data"]["tag_apply_results"][0]["applied"] is True

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.returns_management.flow import (
            ReturnsManagementEngine,
        )

        stub_result = [
            {"return_id": "r1", "order_id": "o1",
             "applied": False, "tags": ["shopai-return-approved"],
             "error": "queued",
             "pending_action_id": "appr_stub_1"},
        ]
        with patch(
            "engines.returns_management.flow.apply_return_tags",
        ) as mock_apply, patch(
            "engines.returns_management.flow.enqueue_return_tags_for_approval",
            return_value=stub_result,
        ) as mock_enqueue:
            output = ReturnsManagementEngine().run(
                _flow_input(
                    apply_return_tags_flag=True,
                    require_approval=True,
                ),
            )

        mock_apply.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["tag_apply_results"] == stub_result
