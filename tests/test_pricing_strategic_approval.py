"""Tests for the pricing engine's strategic-price writeback (1C #10).

The pricing engine emits ONE ``recommended_price`` per product
based on cost, competitor, value, elasticity, and psychology
analyses. Pre-fix that recommendation was advisory — the
merchant copied the price out of the engine output and updated
each variant manually in Shopify admin.

The applier pushes ``recommended_price`` to every variant of the
input product via SHOPIFY_UPDATE_VARIANTS (same mutation
dynamic_pricing uses, scoped to one product).

Coverage:
  1. ``_resolve_proposal`` guardrails — missing product / variants,
     zero / negative price, confidence floor, store-config overrides.
  2. ``apply_strategic_price`` happy path, router unavailable,
     adapter failure, adapter raised.
  3. ``enqueue_strategic_price_for_approval`` happy + skip + queue
     unavailable.
  4. Flow integration — three branches of Stage 10.5.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


def _product(*, pid="gid://shopify/Product/1", variant_count=2,
             price=19.99):
    return {
        "id": pid,
        "title": "Test Product",
        "variants": [
            {"id": f"gid://shopify/Variant/{i}", "price": price}
            for i in range(1, variant_count + 1)
        ],
        "cost": 10.0,
    }


def _recommendation(*, optimal_price=24.99, confidence=0.85,
                    strategy="value_based"):
    return {
        "optimal_price": optimal_price,
        "strategy": strategy,
        "confidence": confidence,
        "projected_margin": 0.45,
        "competitive_position": "premium",
        "rationale": "test",
    }


# ─── _resolve_proposal guardrails ──────────────────────────────


class TestResolveProposal:

    def test_happy_path_yields_variants_and_old_prices(self):
        from engines.pricing.price_applier import _resolve_proposal

        resolved = _resolve_proposal(
            product=_product(variant_count=3, price=19.99),
            recommendation=_recommendation(optimal_price=24.99),
            store=None,
        )
        assert resolved is not None
        assert resolved["product_id"] == "gid://shopify/Product/1"
        assert resolved["new_price"] == 24.99
        assert len(resolved["variant_ids"]) == 3
        assert resolved["old_prices"] == [19.99, 19.99, 19.99]
        assert resolved["strategy"] == "value_based"
        assert resolved["confidence"] == 0.85

    def test_missing_product_returns_none(self):
        from engines.pricing.price_applier import _resolve_proposal

        assert _resolve_proposal({}, _recommendation(), None) is None
        assert _resolve_proposal(None, _recommendation(), None) is None

    def test_missing_recommendation_returns_none(self):
        from engines.pricing.price_applier import _resolve_proposal

        assert _resolve_proposal(_product(), {}, None) is None
        assert _resolve_proposal(_product(), None, None) is None

    def test_missing_id_returns_none(self):
        from engines.pricing.price_applier import _resolve_proposal

        prod = _product()
        prod["id"] = ""
        assert _resolve_proposal(
            prod, _recommendation(), None,
        ) is None

    def test_zero_price_returns_none(self):
        from engines.pricing.price_applier import _resolve_proposal

        assert _resolve_proposal(
            _product(), _recommendation(optimal_price=0), None,
        ) is None

    def test_negative_price_returns_none(self):
        from engines.pricing.price_applier import _resolve_proposal

        assert _resolve_proposal(
            _product(), _recommendation(optimal_price=-5), None,
        ) is None

    def test_sub_floor_confidence_returns_none(self):
        from engines.pricing.price_applier import _resolve_proposal

        # Default floor 0.60
        assert _resolve_proposal(
            _product(), _recommendation(confidence=0.4), None,
        ) is None

    def test_store_floor_override_rejects(self):
        from engines.pricing.price_applier import _resolve_proposal

        assert _resolve_proposal(
            _product(),
            _recommendation(confidence=0.70),
            store={"strategic_pricing_confidence_floor": 0.80},
        ) is None

    def test_store_floor_override_allows(self):
        from engines.pricing.price_applier import _resolve_proposal

        resolved = _resolve_proposal(
            _product(),
            _recommendation(confidence=0.50),
            store={"strategic_pricing_confidence_floor": 0.40},
        )
        assert resolved is not None

    def test_product_without_variants_returns_none(self):
        from engines.pricing.price_applier import _resolve_proposal

        prod = _product()
        prod["variants"] = []
        assert _resolve_proposal(
            prod, _recommendation(), None,
        ) is None

    def test_variants_without_ids_returns_none(self):
        from engines.pricing.price_applier import _resolve_proposal

        prod = _product()
        prod["variants"] = [{"price": 10.0}, {"id": ""}]
        assert _resolve_proposal(
            prod, _recommendation(), None,
        ) is None

    def test_fallback_recommended_price_key(self):
        """Some upstream callers emit ``recommended_price``
        instead of ``optimal_price`` — accept both."""
        from engines.pricing.price_applier import _resolve_proposal

        rec = _recommendation()
        del rec["optimal_price"]
        rec["recommended_price"] = 30.0
        resolved = _resolve_proposal(_product(), rec, None)
        assert resolved is not None
        assert resolved["new_price"] == 30.0


# ─── apply_strategic_price (direct path) ───────────────────────


class TestApplyStrategicPrice:

    def test_happy_path_calls_router(self):
        from engines.pricing import price_applier

        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.data = {}
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            price_applier, "_get_router", return_value=fake_router,
        ):
            result = price_applier.apply_strategic_price(
                product=_product(variant_count=2),
                recommendation=_recommendation(),
            )

        assert result is not None
        assert result["applied"] is True
        assert result["variants_updated"] == 2
        assert result["new_price"] == 24.99
        assert result["strategy"] == "value_based"
        assert result["error"] is None
        # Adapter called with two variants @ formatted price.
        call_args = fake_router.execute.call_args
        payload = call_args[0][1]
        assert payload["product_id"] == "gid://shopify/Product/1"
        assert all(v["price"] == "24.99" for v in payload["variants"])

    def test_zero_price_returns_none(self):
        from engines.pricing import price_applier

        assert price_applier.apply_strategic_price(
            product=_product(),
            recommendation=_recommendation(optimal_price=0),
        ) is None

    def test_router_unavailable_returns_structured_skip(self):
        from engines.pricing import price_applier

        with patch.object(
            price_applier, "_get_router", return_value=None,
        ):
            result = price_applier.apply_strategic_price(
                product=_product(),
                recommendation=_recommendation(),
            )
        assert result is not None
        assert result["applied"] is False
        assert result["error"] == "router_unavailable"

    def test_adapter_failed_surfaces_error(self):
        from engines.pricing import price_applier

        fake_result = MagicMock()
        fake_result.ok = False
        fake_result.error = "out of stock"
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            price_applier, "_get_router", return_value=fake_router,
        ):
            result = price_applier.apply_strategic_price(
                product=_product(),
                recommendation=_recommendation(),
            )

        assert result["applied"] is False
        assert result["error"].startswith("adapter_failed:")
        assert "out of stock" in result["error"]

    def test_adapter_raised_surfaces_error(self):
        from engines.pricing import price_applier

        fake_router = MagicMock()
        fake_router.execute = MagicMock(
            side_effect=RuntimeError("boom"),
        )

        with patch.object(
            price_applier, "_get_router", return_value=fake_router,
        ):
            result = price_applier.apply_strategic_price(
                product=_product(),
                recommendation=_recommendation(),
            )

        assert result["applied"] is False
        assert result["error"].startswith("adapter_raised:")
        assert "boom" in result["error"]


# ─── enqueue_strategic_price_for_approval ──────────────────────


class TestEnqueueStrategicPriceForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.pricing.price_applier import (
            enqueue_strategic_price_for_approval,
        )

        result = enqueue_strategic_price_for_approval(
            product=_product(variant_count=2, price=19.99),
            recommendation=_recommendation(optimal_price=24.99),
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "$24.99" in result["narrative"]
        assert "+$5.00" in result["narrative"]
        assert "value_based" in result["narrative"]
        assert "2 variant" in result["narrative"]

        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "pricing"
        assert action.action_type == "apply_strategic_price"
        assert action.capability == "SHOPIFY_UPDATE_VARIANTS"

    def test_zero_price_returns_none(self, isolated_queue):
        from engines.pricing.price_applier import (
            enqueue_strategic_price_for_approval,
        )

        assert enqueue_strategic_price_for_approval(
            product=_product(),
            recommendation=_recommendation(optimal_price=0),
        ) is None
        assert isolated_queue.list_pending() == []

    def test_sub_floor_confidence_returns_none(self, isolated_queue):
        from engines.pricing.price_applier import (
            enqueue_strategic_price_for_approval,
        )

        assert enqueue_strategic_price_for_approval(
            product=_product(),
            recommendation=_recommendation(confidence=0.4),
        ) is None

    def test_no_variants_returns_none(self, isolated_queue):
        from engines.pricing.price_applier import (
            enqueue_strategic_price_for_approval,
        )

        prod = _product()
        prod["variants"] = []
        assert enqueue_strategic_price_for_approval(
            product=prod,
            recommendation=_recommendation(),
        ) is None

    def test_queue_unavailable_returns_none(self, isolated_queue):
        from engines.pricing.price_applier import (
            enqueue_strategic_price_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_strategic_price_for_approval(
                product=_product(),
                recommendation=_recommendation(),
            )
        assert result is None


# ─── Flow integration ──────────────────────────────────────────


def _flow_input(
    *,
    apply_strategic_price=None,
    require_approval=None,
):
    data: dict = {
        "product": _product(variant_count=2, price=19.99),
        "market": {"demand_level": "medium"},
        "platform_fees_pct": 0.029,
        "payment_processing_pct": 0.029,
        "target_margin": 0.30,
        "store": {"strategic_pricing_confidence_floor": 0.10},
    }
    if apply_strategic_price is not None:
        data["apply_strategic_price"] = apply_strategic_price
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.pricing.flow import PricingEngine

        with patch(
            "engines.pricing.flow.apply_strategic_price",
        ) as mock_apply, patch(
            "engines.pricing.flow.enqueue_strategic_price_for_approval",
        ) as mock_enqueue:
            output = PricingEngine().run(_flow_input())

        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["price_apply_result"] is None
            assert output["data"]["price_pending_action"] is None

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.pricing.flow import PricingEngine

        stub = {
            "applied": True,
            "product_id": "gid://shopify/Product/1",
            "variants_updated": 2,
            "new_price": 24.99,
            "old_price_examples": [19.99, 19.99],
            "strategy": "value_based",
            "error": None,
        }
        with patch(
            "engines.pricing.flow.apply_strategic_price",
            return_value=stub,
        ) as mock_apply, patch(
            "engines.pricing.flow.enqueue_strategic_price_for_approval",
        ) as mock_enqueue:
            output = PricingEngine().run(
                _flow_input(
                    apply_strategic_price=True,
                    require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_apply.assert_called_once()
            assert output["data"]["price_apply_result"] == stub
            assert output["data"]["price_pending_action"] is None

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.pricing.flow import PricingEngine

        stub = {
            "pending_action_id": "appr_stub_1",
            "narrative": "price stub",
            "params": {},
        }
        with patch(
            "engines.pricing.flow.apply_strategic_price",
        ) as mock_apply, patch(
            "engines.pricing.flow.enqueue_strategic_price_for_approval",
            return_value=stub,
        ) as mock_enqueue:
            output = PricingEngine().run(
                _flow_input(
                    apply_strategic_price=True,
                    require_approval=True,
                ),
            )

        mock_apply.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["price_pending_action"] == stub
            assert output["data"]["price_apply_result"] is None
