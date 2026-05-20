"""Tests for ``engines.product_filter.tag_applier``.

Pushes ``shopai-filter-rejected-{reason}`` tags on each
rejected product via SHOPIFY_ADD_TAGS. Two paths (queue /
direct) selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product id / "unknown" literal skipped / unknown stage
     skipped / dedup / each stage maps to correct slug).
  2. Direct path: SHOPIFY_ADD_TAGS called per rejection;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each rejection enqueues with correct params;
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

from engines.product_filter.tag_applier import (
    apply_filter_tags,
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


def _rejected(
    *,
    pid="gid://shopify/Product/1",
    stage="margin_filter",
    reason_text="Margin 8.0% below minimum 15.0%",
):
    return {
        "id": pid,
        "title": "Test",
        "rejection_stage": stage,
        "rejection_reason": reason_text,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_filter_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_filter_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_filter_tags(
            ["bad", 42, _rejected(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_id_skipped(self, isolated_queue):
        results = apply_filter_tags(
            [_rejected(pid="")],
        )
        assert results == []

    def test_unknown_id_skipped(self, isolated_queue):
        # The engine uses "unknown" as a default; not a real id.
        results = apply_filter_tags(
            [_rejected(pid="unknown")],
        )
        assert results == []

    def test_unknown_stage_skipped(self, isolated_queue):
        # Defensive guard against hand-built test data or
        # future engine stages that this applier hasn't
        # learned about yet.
        results = apply_filter_tags(
            [_rejected(stage="unknown_filter")],
        )
        assert results == []

    def test_each_stage_maps_to_correct_slug(self, isolated_queue):
        results = apply_filter_tags(
            [
                _rejected(pid="gid://p/1", stage="margin_filter"),
                _rejected(pid="gid://p/2", stage="legal_filter"),
                _rejected(pid="gid://p/3", stage="shipping_filter"),
                _rejected(pid="gid://p/4", stage="brand_filter"),
            ],
        )
        tags = {r["product_id"]: r["tag"] for r in results}
        assert tags == {
            "gid://p/1": "shopai-filter-rejected-margin",
            "gid://p/2": "shopai-filter-rejected-legal",
            "gid://p/3": "shopai-filter-rejected-shipping",
            "gid://p/4": "shopai-filter-rejected-brand",
        }

    def test_duplicate_product_ids_deduped(self, isolated_queue):
        # First rejection wins — same product can't appear
        # twice in production (stages short-circuit) but be
        # defensive against hand-built data.
        results = apply_filter_tags(
            [
                _rejected(pid="gid://p/1", stage="margin_filter"),
                _rejected(pid="gid://p/1", stage="legal_filter"),  # dup
            ],
        )
        assert len(results) == 1
        assert results[0]["tag"] == "shopai-filter-rejected-margin"


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, rejected, **kwargs):
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
            results = apply_filter_tags(
                rejected, require_approval=False, **kwargs,
            )
        return results, captured

    def test_rejected_product_tagged(self):
        results, captured = self._run_direct([_rejected()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-filter-rejected-margin"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_filter_tags(
                [_rejected()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert results[0]["error"] == "router_unavailable"

    def test_adapter_failure_per_product_error(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_filter_tags(
                [_rejected()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "rate_limited" in results[0]["error"]

    def test_adapter_raise_per_product_error(self):
        def _raises(c, p):
            raise RuntimeError("boom")
        router = SimpleNamespace(execute=_raises)
        with patch(
            "core.adapters.get_router", return_value=router,
        ):
            results = apply_filter_tags(
                [_rejected()], require_approval=False,
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
            results = apply_filter_tags(
                [
                    _rejected(pid="gid://p/1"),
                    _rejected(pid="gid://p/2"),
                    _rejected(pid="gid://p/3"),
                ],
                require_approval=False,
            )
        assert len(results) == 3
        assert results[0]["applied"] is True
        assert results[1]["applied"] is False
        assert results[2]["applied"] is True


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_each_rejection_enqueues(self, isolated_queue):
        results = apply_filter_tags([
            _rejected(pid="gid://p/1", stage="margin_filter"),
            _rejected(pid="gid://p/2", stage="brand_filter"),
        ])
        assert len(results) == 2
        assert all("pending_action_id" in r for r in results)
        assert all(r["applied"] is False for r in results)
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-filter-rejected-margin"
        assert action.params["reason"] == "margin"
        assert action.params["rejection_stage"] == "margin_filter"
        assert action.action_type == "tag_filter_rejected"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_filter_tags([_rejected()])
        assert results[0]["applied"] is False
        assert results[0]["error"] == "approval_queue_unavailable"

    def test_enqueue_raise_per_product(self, isolated_queue):
        original = isolated_queue.enqueue
        call_count = {"n": 0}

        def _enqueue(**kw):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("boom")
            return original(**kw)

        isolated_queue.enqueue = _enqueue
        results = apply_filter_tags([
            _rejected(pid="gid://p/1"),
            _rejected(pid="gid://p/2"),
            _rejected(pid="gid://p/3"),
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
            "engines.product_filter.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_filter_tags(
                [_rejected()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "product_filter"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.product_filter.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_filter_tags(
                [_rejected()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.product_filter.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_filter_tags([_rejected()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(self, *, apply=False, require_approval=None):
        # One product with low margin (rejected) and one
        # with healthy margin (accepted).
        products = [
            {
                "id": "gid://shopify/Product/1",
                "title": "Low margin",
                "sale_price": 10.0,
                "unit_cost": 9.5,  # 5% margin — rejected
                "weight_kg": 1.0,
            },
            {
                "id": "gid://shopify/Product/2",
                "title": "Healthy",
                "sale_price": 20.0,
                "unit_cost": 10.0,  # 50% margin — passes
                "weight_kg": 1.0,
            },
        ]
        data = {
            "products": products,
            "criteria": {"min_margin_pct": 15.0},
        }
        if apply:
            data["apply_filter_tags"] = True
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
        from engines.product_filter.flow import (
            ProductFilterEngine,
        )
        with patch(
            "engines.product_filter.tag_applier.apply_filter_tags",
        ) as applier_mock:
            result = ProductFilterEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.product_filter.flow import (
            ProductFilterEngine,
        )
        with patch(
            "engines.product_filter.tag_applier.apply_filter_tags",
            return_value=[
                {"product_id": "gid://shopify/Product/1",
                 "rejection_stage": "margin_filter",
                 "reason": "margin",
                 "tag": "shopai-filter-rejected-margin",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ProductFilterEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Default require_approval=True propagates
        assert kwargs["require_approval"] is True
        # First positional arg is the rejected_products list
        positional = applier_mock.call_args.args
        # At least one product should have been rejected
        assert len(positional[0]) >= 1
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.product_filter.flow import (
            ProductFilterEngine,
        )
        with patch(
            "engines.product_filter.tag_applier.apply_filter_tags",
            return_value=[],
        ) as applier_mock:
            ProductFilterEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False
