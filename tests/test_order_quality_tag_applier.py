"""Tests for ``engines.order_quality.tag_applier``.

Pushes ``shopai-defect-high-rate`` tags on products with
defect rates above threshold via SHOPIFY_ADD_TAGS. Two paths
(queue / direct) selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / supplier
     rollups skipped / missing entity / below threshold /
     case-insensitive entity_type / dedup keeps worst).
  2. Direct path: SHOPIFY_ADD_TAGS called per defective product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each defective product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / min_defect_rate propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.order_quality.tag_applier import (
    apply_quality_tags,
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


def _rate(
    *,
    entity="gid://shopify/Product/1",
    entity_type="product",
    rate=0.15,
    count=3,
    total=20,
):
    return {
        "entity": entity,
        "entity_type": entity_type,
        "total_orders": total,
        "defect_count": count,
        "defect_rate": rate,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_quality_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_quality_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_quality_tags(
            ["bad", 42, _rate(entity="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_supplier_rollups_skipped(self, isolated_queue):
        # Supplier entries have entity_type="supplier" — we
        # don't tag arbitrary supplier strings; only PRODUCTS.
        results = apply_quality_tags(
            [
                _rate(entity_type="supplier", entity="ACME Co"),
                _rate(entity_type="product",
                      entity="gid://p/1"),
            ],
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/1"

    def test_missing_entity_skipped(self, isolated_queue):
        results = apply_quality_tags(
            [_rate(entity="")],
        )
        assert results == []

    def test_below_threshold_skipped(self, isolated_queue):
        # Default threshold is 0.10 (10%); 5% should be
        # filtered out.
        results = apply_quality_tags(
            [_rate(rate=0.05)],
        )
        assert results == []

    def test_threshold_boundary_included(self, isolated_queue):
        # Exactly 0.10 = at-threshold → included.
        results = apply_quality_tags(
            [_rate(rate=0.10)],
        )
        assert len(results) == 1

    def test_case_insensitive_entity_type(self, isolated_queue):
        # The engine emits lowercase but tolerate any case.
        results = apply_quality_tags(
            [
                _rate(entity_type="PRODUCT",
                      entity="gid://p/1"),
                _rate(entity_type="Product",
                      entity="gid://p/2"),
            ],
        )
        assert len(results) == 2

    def test_dedup_keeps_worst_rate(self, isolated_queue):
        # Same product appears twice; higher rate wins.
        results = apply_quality_tags(
            [
                _rate(entity="gid://p/1", rate=0.12),
                _rate(entity="gid://p/1", rate=0.25),
            ],
        )
        assert len(results) == 1
        assert results[0]["defect_rate"] == 0.25

    def test_custom_min_defect_rate(self, isolated_queue):
        # Raise threshold to 0.20 — only products at or above
        # that get tagged.
        results = apply_quality_tags(
            [
                _rate(entity="gid://p/1", rate=0.12),
                _rate(entity="gid://p/2", rate=0.25),
            ],
            min_defect_rate=0.20,
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/2"

    def test_bad_rate_coerced_to_zero(self, isolated_queue):
        # Bad numeric in defect_rate → 0.0, which is below the
        # default threshold of 0.10 → skipped.
        results = apply_quality_tags(
            [{
                "entity": "gid://p/1",
                "entity_type": "product",
                "defect_rate": "high",
            }],
        )
        assert results == []


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, rates, **kwargs):
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
            results = apply_quality_tags(
                rates, require_approval=False, **kwargs,
            )
        return results, captured

    def test_defective_product_tagged(self):
        results, captured = self._run_direct([_rate()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-defect-high-rate"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_quality_tags(
                [_rate()], require_approval=False,
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
            results = apply_quality_tags(
                [_rate()], require_approval=False,
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
            results = apply_quality_tags(
                [_rate()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_defective_product_enqueues(self, isolated_queue):
        results = apply_quality_tags([
            _rate(entity="gid://p/1", rate=0.20,
                  count=4, total=20),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-defect-high-rate"
        assert action.params["defect_rate"] == 0.20
        assert action.params["defect_count"] == 4
        assert action.params["total_orders"] == 20
        assert action.action_type == "tag_defect_high_rate"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_quality_tags([_rate()])
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
        results = apply_quality_tags([
            _rate(entity="gid://p/1"),
            _rate(entity="gid://p/2"),
            _rate(entity="gid://p/3"),
        ])
        failed = [
            r for r in results
            if r.get("error") and "enqueue_raised" in r["error"]
        ]
        assert len(failed) == 1


# ─── Pattern Z ───────────────────────────────────────────────


class TestRecordWritebackIntegration:

    def test_record_called_on_direct_success(self):
        router = SimpleNamespace(execute=lambda c, p: _ok())
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ) as record_mock:
            apply_quality_tags(
                [_rate()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "order_quality"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.order_quality.tag_applier.record_writeback",
        ) as record_mock:
            apply_quality_tags(
                [_rate()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.order_quality.tag_applier.record_writeback",
        ) as record_mock:
            apply_quality_tags([_rate()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        min_defect_rate=None,
    ):
        # 20 orders for one product, 4 of them have defects
        # → 20% defect rate, well above 10% threshold.
        orders = [
            {"id": f"gid://o/{i}",
             "line_items": [{"product_id": "gid://p/1"}]}
            for i in range(1, 21)
        ]
        defects = [
            {"order_id": f"gid://o/{i}",
             "product_id": "gid://p/1",
             "type": "broken",
             "severity": "high"}
            for i in range(1, 5)
        ]
        data = {
            "orders": orders,
            "defects": defects,
            "suppliers": [],
        }
        if apply:
            data["apply_quality_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if min_defect_rate is not None:
            data["min_defect_rate"] = min_defect_rate
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.order_quality.flow import OrderQualityEngine
        with patch(
            "engines.order_quality.tag_applier."
            "apply_quality_tags",
        ) as applier_mock:
            result = OrderQualityEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.order_quality.flow import OrderQualityEngine
        with patch(
            "engines.order_quality.tag_applier."
            "apply_quality_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "defect_rate": 0.20,
                 "defect_count": 4,
                 "total_orders": 20,
                 "tag": "shopai-defect-high-rate",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = OrderQualityEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["min_defect_rate"] == 0.10
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.order_quality.flow import OrderQualityEngine
        with patch(
            "engines.order_quality.tag_applier."
            "apply_quality_tags",
            return_value=[],
        ) as applier_mock:
            OrderQualityEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_min_defect_rate_propagates(self, isolated_queue):
        from engines.order_quality.flow import OrderQualityEngine
        with patch(
            "engines.order_quality.tag_applier."
            "apply_quality_tags",
            return_value=[],
        ) as applier_mock:
            OrderQualityEngine().run(
                self._input(apply=True, min_defect_rate=0.25),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["min_defect_rate"] == 0.25
