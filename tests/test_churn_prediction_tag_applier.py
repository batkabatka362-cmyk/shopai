"""Tests for ``engines.churn_prediction.tag_applier``.

The applier wraps the engine's churn predictions in an opt-in
Shopify tag-customer call. ``critical`` and ``high`` risk
customers get a ``shopai-churn-{level}`` tag pushed via
``SHOPIFY_TAG_CUSTOMER``. Two paths (queue / direct) selected
by ``require_approval``.

Coverage:
  1. Empty / non-list input.
  2. Filter: only critical + high are tagged (medium / low
     skipped).
  3. Missing customer_id skipped silently.
  4. Direct path: SHOPIFY_TAG_CUSTOMER called with correct
     params; success / failure / raise all handled.
  5. Queue path: each elevated-risk prediction enqueues a
     pending_action; queue unavailable returns
     approval_queue_unavailable.
  6. Pattern Z: record_writeback called on every outcome
     (success or failure, queue or direct).
  7. Flow integration: ``data.apply_at_risk_tags`` opt-in
     routes through; default OFF leaves tag_results empty.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.churn_prediction.tag_applier import (
    apply_at_risk_tags,
)


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    """Fresh approval queue per test."""
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


def _pred(*, cid="gid://shopify/Customer/1", level="high", prob=0.8):
    return {
        "customer_id": cid,
        "risk_level": level,
        "churn_probability": prob,
        "key_factors": [],
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_at_risk_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_at_risk_tags(None) == []  # type: ignore

    def test_low_risk_skipped(self, isolated_queue):
        results = apply_at_risk_tags(
            [_pred(level="low"), _pred(level="medium")],
        )
        assert results == []

    def test_missing_customer_id_skipped(self, isolated_queue):
        results = apply_at_risk_tags(
            [_pred(cid="", level="critical")],
        )
        assert results == []

    def test_non_dict_prediction_skipped(self, isolated_queue):
        results = apply_at_risk_tags(
            ["not a dict", 42, _pred(level="critical")],  # type: ignore
        )
        # The one valid critical-risk prediction goes through
        assert len(results) == 1


# ─── Direct path (require_approval=False) ─────────────────────


class TestDirectPath:

    def test_direct_apply_calls_router_with_tag(self):
        captured = {}

        def _exec(cap, params):
            captured["cap"] = cap
            captured["params"] = params
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_at_risk_tags(
                [_pred(level="high")],
                require_approval=False,
            )
        assert captured["cap"].name == "SHOPIFY_TAG_CUSTOMER"
        assert captured["params"]["tags"] == ["shopai-churn-high"]
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-churn-high"

    def test_direct_apply_critical_uses_critical_tag(self):
        captured = {}

        def _exec(cap, params):
            captured["params"] = params
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            apply_at_risk_tags(
                [_pred(level="critical")],
                require_approval=False,
            )
        assert captured["params"]["tags"] == ["shopai-churn-critical"]

    def test_router_unavailable_returns_error_per_customer(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_at_risk_tags(
                [_pred(level="high")],
                require_approval=False,
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_adapter_failure_recorded_per_customer(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_at_risk_tags(
                [_pred(level="high")],
                require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "rate_limited" in results[0]["error"]

    def test_adapter_raise_recorded_per_customer(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_at_risk_tags(
                [_pred(level="high")],
                require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]

    def test_batch_continues_through_per_customer_failure(self):
        """One customer's adapter raise doesn't abort the batch."""
        call_count = {"n": 0}

        def _exec(cap, params):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("transient")
            return _ok()

        router = SimpleNamespace(execute=_exec)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_at_risk_tags(
                [
                    _pred(cid="gid://c/1", level="high"),
                    _pred(cid="gid://c/2", level="high"),
                    _pred(cid="gid://c/3", level="high"),
                ],
                require_approval=False,
            )
        assert len(results) == 3
        assert results[0]["applied"] is True
        assert results[1]["applied"] is False
        assert results[2]["applied"] is True


# ─── Queue path (require_approval=True, default) ──────────────


class TestQueuePath:

    def test_each_elevated_risk_enqueues(self, isolated_queue):
        results = apply_at_risk_tags(
            [
                _pred(cid="gid://c/1", level="critical"),
                _pred(cid="gid://c/2", level="high"),
                _pred(cid="gid://c/3", level="low"),  # skipped
            ],
        )
        assert len(results) == 2
        assert all("pending_action_id" in r for r in results)
        # ``applied`` is False -- queue path doesn't apply
        # immediately; the dispatcher executes after approval.
        assert all(r["applied"] is False for r in results)

    def test_queue_unavailable_records_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_at_risk_tags(
                [_pred(level="high")],
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_enqueue_raise_records_per_customer(self, isolated_queue):
        # Make queue.enqueue raise on the second call
        original = isolated_queue.enqueue
        call_count = {"n": 0}

        def _enqueue(**kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")
            return original(**kw)

        isolated_queue.enqueue = _enqueue
        results = apply_at_risk_tags([
            _pred(cid="gid://c/1", level="high"),
            _pred(cid="gid://c/2", level="high"),
            _pred(cid="gid://c/3", level="high"),
        ])
        assert len(results) == 3
        # First + third succeeded; second raised
        assert "pending_action_id" in results[0]
        assert "enqueue_raised" in results[1]["error"]
        assert "pending_action_id" in results[2]


# ─── Pattern Z: record_writeback fires every outcome ──────────


class TestRecordWritebackIntegration:

    def test_record_called_on_direct_success(self):
        router = SimpleNamespace(
            execute=lambda c, p: _ok(),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.churn_prediction.tag_applier.record_writeback",
        ) as record_mock:
            apply_at_risk_tags(
                [_pred(level="high")],
                require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "churn_prediction"
        assert kwargs["capability"] == "SHOPIFY_TAG_CUSTOMER"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(execute=lambda c, p: _fail("nope"))
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.churn_prediction.tag_applier.record_writeback",
        ) as record_mock:
            apply_at_risk_tags(
                [_pred(level="high")],
                require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["success"] is False
        assert "nope" in kwargs["error"]

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.churn_prediction.tag_applier.record_writeback",
        ) as record_mock:
            apply_at_risk_tags([_pred(level="high")])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ─────────────────────────────────────────


class TestFlowIntegration:

    def test_default_off_keeps_tag_results_empty(self, isolated_queue):
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )

        with patch(
            "engines.churn_prediction.tag_applier.apply_at_risk_tags",
        ) as applier_mock:
            result = ChurnPredictionEngine().run({
                "status": "success",
                "data": {
                    "customers": [{
                        "id": "gid://shopify/Customer/1",
                        "email": "a@b.com",
                        "orders_total": 5,
                    }],
                },
                "meta": {},
                "error": None,
            })
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )

        with patch(
            "engines.churn_prediction.tag_applier.apply_at_risk_tags",
            return_value=[
                {"customer_id": "gid://c/1",
                 "risk_level": "high",
                 "tag": "shopai-churn-high",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ChurnPredictionEngine().run({
                "status": "success",
                "data": {
                    "customers": [{
                        "id": "gid://shopify/Customer/1",
                        "email": "a@b.com",
                        "orders_total": 5,
                    }],
                    "apply_at_risk_tags": True,
                },
                "meta": {},
                "error": None,
            })
        applier_mock.assert_called_once()
        # Default require_approval=True propagates
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is True
        # Tag results land in the engine envelope
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )

        with patch(
            "engines.churn_prediction.tag_applier.apply_at_risk_tags",
            return_value=[],
        ) as applier_mock:
            ChurnPredictionEngine().run({
                "status": "success",
                "data": {
                    "customers": [{
                        "id": "gid://shopify/Customer/1",
                        "email": "a@b.com",
                        "orders_total": 5,
                    }],
                    "apply_at_risk_tags": True,
                    "require_approval": False,
                },
                "meta": {},
                "error": None,
            })
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False
