"""Tests for ``engines.profitability_calculator.tag_applier``.

Pushes ``shopai-margin-{high|negative}`` tags on flagged
products via SHOPIFY_ADD_TAGS. Two paths (queue / direct)
selected by ``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / "unknown" literal / middle-band skipped /
     custom min_margin / negative gated by include_negative /
     dedup keeps highest margin / bad numerics).
  2. Direct path: SHOPIFY_ADD_TAGS called per flagged
     product; router unavailable, adapter failure, raise all
     handled.
  3. Queue path: each flagged product enqueues with correct
     params; queue unavailable; per-enqueue raise doesn't
     abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / min_margin / loss_margin /
     include_negative propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.profitability_calculator.tag_applier import (
    apply_margin_tags,
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


def _prof(
    *,
    pid="gid://shopify/Product/1",
    margin=0.55,
    roi=1.2,
    revenue=1000.0,
):
    return {
        "product_id": pid,
        "revenue": revenue,
        "total_cost": revenue * (1 - margin),
        "net_margin": margin,
        "break_even_units": 50,
        "roi": roi,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_margin_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_margin_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_margin_tags(
            ["bad", 42, _prof(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_margin_tags(
            [_prof(pid="")],
        )
        assert results == []

    def test_unknown_product_id_skipped(self, isolated_queue):
        results = apply_margin_tags(
            [_prof(pid="unknown")],
        )
        assert results == []

    def test_middle_band_skipped(self, isolated_queue):
        # Default min_margin=0.40; loss_margin=0.0.
        # margin=0.20 is in the middle band → no tag.
        results = apply_margin_tags(
            [_prof(margin=0.20)],
        )
        assert results == []

    def test_high_margin_tagged(self, isolated_queue):
        results = apply_margin_tags(
            [_prof(margin=0.55)],
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "high"
        assert results[0]["tag"] == "shopai-margin-high"

    def test_threshold_boundary_high(self, isolated_queue):
        # Exactly 0.40 = at-threshold → high.
        results = apply_margin_tags(
            [_prof(margin=0.40)],
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "high"

    def test_negative_not_tagged_by_default(self, isolated_queue):
        results = apply_margin_tags(
            [_prof(margin=-0.10)],
        )
        assert results == []

    def test_negative_opt_in(self, isolated_queue):
        results = apply_margin_tags(
            [_prof(margin=-0.10)],
            include_negative=True,
        )
        assert len(results) == 1
        assert results[0]["bucket"] == "negative"
        assert results[0]["tag"] == "shopai-margin-negative"

    def test_custom_min_margin(self, isolated_queue):
        results = apply_margin_tags(
            [
                _prof(pid="gid://p/1", margin=0.40),
                _prof(pid="gid://p/2", margin=0.65),
            ],
            min_margin=0.60,
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/2"

    def test_custom_loss_margin(self, isolated_queue):
        # Set loss_margin to 0.05 — anything below 5% margin
        # qualifies as "loss" (still profitable but barely).
        results = apply_margin_tags(
            [
                _prof(pid="gid://p/1", margin=0.03),
                _prof(pid="gid://p/2", margin=0.10),
            ],
            loss_margin=0.05, include_negative=True,
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/1"
        assert results[0]["bucket"] == "negative"

    def test_dedup_keeps_highest_margin(self, isolated_queue):
        results = apply_margin_tags(
            [
                _prof(pid="gid://p/1", margin=0.45),
                _prof(pid="gid://p/1", margin=0.65),
            ],
        )
        assert len(results) == 1
        assert results[0]["net_margin"] == 0.65

    def test_bad_margin_skipped(self, isolated_queue):
        # Non-numeric margin → can't classify → skip.
        results = apply_margin_tags(
            [{"product_id": "gid://p/1",
              "net_margin": "high"}],
        )
        assert results == []


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, prof, **kwargs):
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
            results = apply_margin_tags(
                prof, require_approval=False, **kwargs,
            )
        return results, captured

    def test_high_margin_product_tagged(self):
        results, captured = self._run_direct([_prof()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-margin-high"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_margin_tags(
                [_prof()], require_approval=False,
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
            results = apply_margin_tags(
                [_prof()], require_approval=False,
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
            results = apply_margin_tags(
                [_prof()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_high_margin_product_enqueues(self, isolated_queue):
        results = apply_margin_tags([
            _prof(pid="gid://p/1", margin=0.6, roi=1.5,
                  revenue=2000.0),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-margin-high"
        assert action.params["bucket"] == "high"
        assert action.params["net_margin"] == 0.6
        assert action.params["roi"] == 1.5
        assert action.params["revenue"] == 2000.0
        assert action.action_type == "tag_profitability_margin"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_margin_tags([_prof()])
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
        results = apply_margin_tags([
            _prof(pid="gid://p/1"),
            _prof(pid="gid://p/2"),
            _prof(pid="gid://p/3"),
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
            "engines.profitability_calculator.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_margin_tags(
                [_prof()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "profitability_calculator"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.profitability_calculator.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_margin_tags(
                [_prof()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.profitability_calculator.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_margin_tags([_prof()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        min_margin=None, loss_margin=None, include_negative=None,
    ):
        # High-margin product (margin >= 0.40 default)
        data = {
            "products": [
                {"id": "gid://p/1", "title": "Premium",
                 "units_sold": 100,
                 "sale_price": 50.0,
                 "unit_cost": 20.0},
            ],
            "costs": [],
            "pricing": {},
        }
        if apply:
            data["apply_margin_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if min_margin is not None:
            data["min_margin"] = min_margin
        if loss_margin is not None:
            data["loss_margin"] = loss_margin
        if include_negative is not None:
            data["include_negative"] = include_negative
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.profitability_calculator.flow import (
            ProfitabilityCalculatorEngine,
        )
        with patch(
            "engines.profitability_calculator.tag_applier."
            "apply_margin_tags",
        ) as applier_mock:
            result = ProfitabilityCalculatorEngine().run(
                self._input(),
            )
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.profitability_calculator.flow import (
            ProfitabilityCalculatorEngine,
        )
        with patch(
            "engines.profitability_calculator.tag_applier."
            "apply_margin_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "net_margin": 0.6,
                 "bucket": "high",
                 "tag": "shopai-margin-high",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = ProfitabilityCalculatorEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["min_margin"] == 0.40
        assert kwargs["loss_margin"] == 0.0
        assert kwargs["include_negative"] is False
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.profitability_calculator.flow import (
            ProfitabilityCalculatorEngine,
        )
        with patch(
            "engines.profitability_calculator.tag_applier."
            "apply_margin_tags",
            return_value=[],
        ) as applier_mock:
            ProfitabilityCalculatorEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_min_margin_propagates(self, isolated_queue):
        from engines.profitability_calculator.flow import (
            ProfitabilityCalculatorEngine,
        )
        with patch(
            "engines.profitability_calculator.tag_applier."
            "apply_margin_tags",
            return_value=[],
        ) as applier_mock:
            ProfitabilityCalculatorEngine().run(
                self._input(apply=True, min_margin=0.60),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["min_margin"] == 0.60

    def test_include_negative_propagates(self, isolated_queue):
        from engines.profitability_calculator.flow import (
            ProfitabilityCalculatorEngine,
        )
        with patch(
            "engines.profitability_calculator.tag_applier."
            "apply_margin_tags",
            return_value=[],
        ) as applier_mock:
            ProfitabilityCalculatorEngine().run(
                self._input(apply=True, include_negative=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_negative"] is True
