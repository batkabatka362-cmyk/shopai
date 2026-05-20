"""Tests for ``engines.stock_prediction.tag_applier``.

Pushes ``shopai-stock-{urgency}`` tags on at-risk products
via SHOPIFY_ADD_TAGS. Two paths (queue / direct) selected by
``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / non-critical skipped by default / high
     gated by include_high / dedup keeps most-urgent /
     case-insensitive urgency).
  2. Direct path: SHOPIFY_ADD_TAGS called per at-risk product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each at-risk product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / include_high propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.stock_prediction.tag_applier import (
    apply_stock_tags,
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


def _pred(
    *,
    pid="gid://shopify/Product/1",
    urgency="critical",
    qty=50,
    restock_date="2026-05-25",
):
    return {
        "product_id": pid,
        "urgency": urgency,
        "predicted_demand_30d": 100.0,
        "predicted_demand_90d": 300.0,
        "restock_date": restock_date,
        "restock_qty": qty,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_stock_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_stock_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_stock_tags(
            ["bad", 42, _pred(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_stock_tags(
            [_pred(pid="")],
        )
        assert results == []

    def test_only_critical_tagged_by_default(self, isolated_queue):
        results = apply_stock_tags(
            [
                _pred(pid="gid://p/1", urgency="critical"),
                _pred(pid="gid://p/2", urgency="high"),
                _pred(pid="gid://p/3", urgency="medium"),
                _pred(pid="gid://p/4", urgency="low"),
            ],
        )
        assert len(results) == 1
        assert results[0]["urgency"] == "critical"
        assert results[0]["tag"] == "shopai-stock-critical"

    def test_include_high_opts_in(self, isolated_queue):
        results = apply_stock_tags(
            [
                _pred(pid="gid://p/1", urgency="critical"),
                _pred(pid="gid://p/2", urgency="high"),
                _pred(pid="gid://p/3", urgency="medium"),
            ],
            include_high=True,
        )
        assert len(results) == 2
        urgencies = {r["urgency"] for r in results}
        assert urgencies == {"critical", "high"}

    def test_dedup_keeps_most_urgent(self, isolated_queue):
        # Same product appears twice with different urgencies;
        # critical wins over high.
        results = apply_stock_tags(
            [
                _pred(pid="gid://p/1", urgency="high"),
                _pred(pid="gid://p/1", urgency="critical"),
            ],
            include_high=True,
        )
        assert len(results) == 1
        assert results[0]["urgency"] == "critical"

    def test_dedup_first_critical_persists(self, isolated_queue):
        # Critical first, then "high" same id — critical stays
        # (most-urgent wins regardless of order).
        results = apply_stock_tags(
            [
                _pred(pid="gid://p/1", urgency="critical"),
                _pred(pid="gid://p/1", urgency="high"),
            ],
            include_high=True,
        )
        assert len(results) == 1
        assert results[0]["urgency"] == "critical"

    def test_case_insensitive_urgency(self, isolated_queue):
        results = apply_stock_tags(
            [
                _pred(pid="gid://p/1", urgency="CRITICAL"),
                _pred(pid="gid://p/2", urgency="Critical"),
            ],
        )
        assert len(results) == 2


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, predictions, **kwargs):
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
            results = apply_stock_tags(
                predictions, require_approval=False, **kwargs,
            )
        return results, captured

    def test_critical_product_tagged(self):
        results, captured = self._run_direct([_pred()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-stock-critical"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_stock_tags(
                [_pred()], require_approval=False,
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
            results = apply_stock_tags(
                [_pred()], require_approval=False,
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
            results = apply_stock_tags(
                [_pred()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_critical_product_enqueues(self, isolated_queue):
        results = apply_stock_tags([
            _pred(pid="gid://p/1", urgency="critical",
                  qty=50, restock_date="2026-05-25"),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-stock-critical"
        assert action.params["urgency"] == "critical"
        assert action.params["restock_qty"] == 50
        assert action.params["restock_date"] == "2026-05-25"
        assert action.action_type == "tag_stock_at_risk"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_stock_tags([_pred()])
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
        results = apply_stock_tags([
            _pred(pid="gid://p/1"),
            _pred(pid="gid://p/2"),
            _pred(pid="gid://p/3"),
        ])
        # Exactly one should have failed with enqueue_raised
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
            "engines.stock_prediction.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_stock_tags(
                [_pred()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "stock_prediction"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.stock_prediction.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_stock_tags(
                [_pred()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.stock_prediction.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_stock_tags([_pred()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        include_high=None,
    ):
        # Two products: one with current_stock=0 (critical),
        # one with healthy stock.
        data = {
            "products": [
                {"id": "gid://p/1", "title": "Out of stock"},
                {"id": "gid://p/2", "title": "Healthy"},
            ],
            "orders_history": [
                {"product_id": "gid://p/1", "qty": 5,
                 "date": "2026-05-01"},
                {"product_id": "gid://p/1", "qty": 3,
                 "date": "2026-05-10"},
            ],
            "suppliers": [],
            "current_stock": {"gid://p/1": 0, "gid://p/2": 500},
        }
        if apply:
            data["apply_stock_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if include_high is not None:
            data["include_high"] = include_high
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.stock_prediction.flow import (
            StockPredictionEngine,
        )
        with patch(
            "engines.stock_prediction.tag_applier."
            "apply_stock_tags",
        ) as applier_mock:
            result = StockPredictionEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.stock_prediction.flow import (
            StockPredictionEngine,
        )
        with patch(
            "engines.stock_prediction.tag_applier."
            "apply_stock_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "urgency": "critical",
                 "tag": "shopai-stock-critical",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = StockPredictionEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["include_high"] is False
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.stock_prediction.flow import (
            StockPredictionEngine,
        )
        with patch(
            "engines.stock_prediction.tag_applier."
            "apply_stock_tags",
            return_value=[],
        ) as applier_mock:
            StockPredictionEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_include_high_propagates(self, isolated_queue):
        from engines.stock_prediction.flow import (
            StockPredictionEngine,
        )
        with patch(
            "engines.stock_prediction.tag_applier."
            "apply_stock_tags",
            return_value=[],
        ) as applier_mock:
            StockPredictionEngine().run(
                self._input(apply=True, include_high=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_high"] is True

    def test_predictions_carry_urgency(self, isolated_queue):
        # Regression: the engine must forward `urgency` from
        # the recommender into the predictions output so the
        # applier can bucket on it.
        from engines.stock_prediction.flow import (
            StockPredictionEngine,
        )
        result = StockPredictionEngine().run(self._input())
        for p in result["data"]["predictions"]:
            assert "urgency" in p
