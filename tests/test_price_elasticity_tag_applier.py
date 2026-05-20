"""Tests for ``engines.price_elasticity.tag_applier``.

Pushes ``shopai-price-{inelastic|elastic}`` tags on products
via SHOPIFY_ADD_TAGS. Two paths (queue / direct) selected by
``require_approval``.

Coverage:
  1. Input filtering (empty / non-list / non-dict / missing
     product_id / "unknown" literal / missing coefficient /
     elastic gated by include_elastic / dedup keeps
     last-seen).
  2. Direct path: SHOPIFY_ADD_TAGS called per product;
     router unavailable, adapter failure, raise all handled.
  3. Queue path: each product enqueues with correct params;
     queue unavailable; per-enqueue raise doesn't abort.
  4. Pattern Z: record_writeback fires on every outcome.
  5. Flow integration: default off / opt-in calls applier /
     require_approval / include_elastic propagate.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from engines.price_elasticity.tag_applier import (
    apply_elasticity_tags,
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


def _ela(
    *,
    pid="gid://shopify/Product/1",
    coef=0.4,
    is_elastic=False,
    optimal_price=29.99,
):
    return {
        "product_id": pid,
        "coefficient": coef,
        "optimal_price": optimal_price,
        "expected_revenue": 1000.0,
        "is_elastic": is_elastic,
    }


# ─── Input filtering ──────────────────────────────────────────


class TestInputFiltering:

    def test_empty_input(self, isolated_queue):
        assert apply_elasticity_tags([]) == []

    def test_non_list_input(self, isolated_queue):
        assert apply_elasticity_tags(None) == []  # type: ignore

    def test_non_dict_entry_skipped(self, isolated_queue):
        results = apply_elasticity_tags(
            ["bad", 42, _ela(pid="gid://p/2")],  # type: ignore
        )
        assert len(results) == 1

    def test_missing_product_id_skipped(self, isolated_queue):
        results = apply_elasticity_tags(
            [_ela(pid="")],
        )
        assert results == []

    def test_unknown_product_id_skipped(self, isolated_queue):
        results = apply_elasticity_tags(
            [_ela(pid="unknown")],
        )
        assert results == []

    def test_missing_coefficient_skipped(self, isolated_queue):
        # Bad coefficient → skip (can't classify).
        results = apply_elasticity_tags(
            [{"product_id": "gid://p/1",
              "coefficient": "very",
              "is_elastic": False}],
        )
        assert results == []

    def test_inelastic_tagged_by_default(self, isolated_queue):
        results = apply_elasticity_tags(
            [
                _ela(pid="gid://p/1", is_elastic=False),
                _ela(pid="gid://p/2", is_elastic=True),
            ],
        )
        assert len(results) == 1
        assert results[0]["product_id"] == "gid://p/1"
        assert results[0]["bucket"] == "inelastic"
        assert results[0]["tag"] == "shopai-price-inelastic"

    def test_include_elastic_opts_in(self, isolated_queue):
        results = apply_elasticity_tags(
            [
                _ela(pid="gid://p/1", is_elastic=False),
                _ela(pid="gid://p/2", is_elastic=True),
            ],
            include_elastic=True,
        )
        assert len(results) == 2
        buckets = {r["bucket"] for r in results}
        assert buckets == {"inelastic", "elastic"}

    def test_dedup_last_seen_wins(self, isolated_queue):
        # Same product appears twice — last-seen wins.
        results = apply_elasticity_tags(
            [
                _ela(pid="gid://p/1", coef=0.3),
                _ela(pid="gid://p/1", coef=0.5),
            ],
        )
        assert len(results) == 1
        assert results[0]["coefficient"] == 0.5


# ─── Direct path ──────────────────────────────────────────────


class TestDirectPath:

    def _run_direct(self, ela, **kwargs):
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
            results = apply_elasticity_tags(
                ela, require_approval=False, **kwargs,
            )
        return results, captured

    def test_inelastic_product_tagged(self):
        results, captured = self._run_direct([_ela()])
        assert results[0]["applied"] is True
        assert results[0]["tag"] == "shopai-price-inelastic"
        assert captured["calls"][0]["cap"].name == "SHOPIFY_ADD_TAGS"
        assert captured["calls"][0]["params"]["id"] == (
            "gid://shopify/Product/1"
        )

    def test_router_unavailable_per_product_error(self):
        with patch(
            "core.adapters.get_router", return_value=None,
        ):
            results = apply_elasticity_tags(
                [_ela()], require_approval=False,
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
            results = apply_elasticity_tags(
                [_ela()], require_approval=False,
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
            results = apply_elasticity_tags(
                [_ela()], require_approval=False,
            )
        assert results[0]["applied"] is False
        assert "adapter_raised" in results[0]["error"]


# ─── Queue path ──────────────────────────────────────────────


class TestQueuePath:

    def test_inelastic_product_enqueues(self, isolated_queue):
        results = apply_elasticity_tags([
            _ela(pid="gid://p/1", coef=0.4,
                 optimal_price=39.99),
        ])
        assert len(results) == 1
        assert "pending_action_id" in results[0]
        assert results[0]["applied"] is False
        action = isolated_queue.get(
            results[0]["pending_action_id"],
        )
        assert action.params["product_id"] == "gid://p/1"
        assert action.params["tag"] == "shopai-price-inelastic"
        assert action.params["bucket"] == "inelastic"
        assert action.params["coefficient"] == 0.4
        assert action.params["optimal_price"] == 39.99
        assert action.action_type == "tag_price_elasticity"
        assert action.capability == "SHOPIFY_ADD_TAGS"

    def test_queue_unavailable_per_product_error(self):
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            results = apply_elasticity_tags([_ela()])
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
        results = apply_elasticity_tags([
            _ela(pid="gid://p/1"),
            _ela(pid="gid://p/2"),
            _ela(pid="gid://p/3"),
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
            "engines.price_elasticity.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_elasticity_tags(
                [_ela()], require_approval=False,
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "price_elasticity"
        assert kwargs["capability"] == "SHOPIFY_ADD_TAGS"
        assert kwargs["success"] is True

    def test_record_called_on_direct_failure(self):
        router = SimpleNamespace(
            execute=lambda c, p: _fail("rate_limited"),
        )
        with patch(
            "core.adapters.get_router", return_value=router,
        ), patch(
            "engines.price_elasticity.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_elasticity_tags(
                [_ela()], require_approval=False,
            )
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False

    def test_record_called_on_queue_enqueue(self, isolated_queue):
        with patch(
            "engines.price_elasticity.tag_applier."
            "record_writeback",
        ) as record_mock:
            apply_elasticity_tags([_ela()])
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is True


# ─── Flow integration ────────────────────────────────────────


class TestFlowIntegration:

    def _input(
        self, *, apply=False, require_approval=None,
        include_elastic=None,
    ):
        data = {
            "products": [
                {"id": "gid://p/1", "title": "Premium",
                 "sale_price": 30.0,
                 "unit_cost": 12.0,
                 "units_sold": 80,
                 "price_history": [
                     {"price": 25.0, "units": 90},
                     {"price": 35.0, "units": 75},
                 ]},
            ],
            "sales_history": [],
            "competitor_prices": [],
        }
        if apply:
            data["apply_elasticity_tags"] = True
        if require_approval is not None:
            data["require_approval"] = require_approval
        if include_elastic is not None:
            data["include_elastic"] = include_elastic
        return {
            "status": "success",
            "data": data,
            "meta": {},
            "error": None,
        }

    def test_default_off_keeps_tag_results_empty(
        self, isolated_queue,
    ):
        from engines.price_elasticity.flow import (
            PriceElasticityEngine,
        )
        with patch(
            "engines.price_elasticity.tag_applier."
            "apply_elasticity_tags",
        ) as applier_mock:
            result = PriceElasticityEngine().run(self._input())
        applier_mock.assert_not_called()
        assert result["data"]["tag_results"] == []

    def test_opt_in_calls_applier(self, isolated_queue):
        from engines.price_elasticity.flow import (
            PriceElasticityEngine,
        )
        with patch(
            "engines.price_elasticity.tag_applier."
            "apply_elasticity_tags",
            return_value=[
                {"product_id": "gid://p/1",
                 "coefficient": 0.4,
                 "bucket": "inelastic",
                 "tag": "shopai-price-inelastic",
                 "applied": True, "error": None},
            ],
        ) as applier_mock:
            result = PriceElasticityEngine().run(
                self._input(apply=True),
            )
        applier_mock.assert_called_once()
        kwargs = applier_mock.call_args.kwargs
        # Defaults propagate
        assert kwargs["require_approval"] is True
        assert kwargs["include_elastic"] is False
        assert len(result["data"]["tag_results"]) == 1

    def test_explicit_require_approval_false_propagates(
        self, isolated_queue,
    ):
        from engines.price_elasticity.flow import (
            PriceElasticityEngine,
        )
        with patch(
            "engines.price_elasticity.tag_applier."
            "apply_elasticity_tags",
            return_value=[],
        ) as applier_mock:
            PriceElasticityEngine().run(
                self._input(apply=True, require_approval=False),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["require_approval"] is False

    def test_include_elastic_propagates(self, isolated_queue):
        from engines.price_elasticity.flow import (
            PriceElasticityEngine,
        )
        with patch(
            "engines.price_elasticity.tag_applier."
            "apply_elasticity_tags",
            return_value=[],
        ) as applier_mock:
            PriceElasticityEngine().run(
                self._input(apply=True, include_elastic=True),
            )
        kwargs = applier_mock.call_args.kwargs
        assert kwargs["include_elastic"] is True
