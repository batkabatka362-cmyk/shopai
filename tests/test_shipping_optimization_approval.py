"""Tests for the shipping_optimization approval-queue wiring (1C #8).

The engine's strategy_recommender output ranks four candidate
strategies; only ``free_over_threshold`` maps to a single
Shopify mutation (``SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING``).
The applier mints when the winner is that strategy, the
threshold is positive, and confidence clears the floor.

Coverage:
  1. ``_build_proposal`` guardrails — strategy_id, threshold,
     confidence floor, ttl resolution.
  2. ``apply_shipping_strategy`` happy path, router unavailable,
     adapter failure, adapter raised.
  3. ``enqueue_shipping_for_approval`` happy path, queue
     unavailable, wrong-strategy short-circuit.
  4. flow integration — three branches of Stage 8.5.
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


def _recommendation(
    *,
    strategy_id: str = "free_over_threshold",
    threshold: float = 75.0,
    confidence: float = 0.80,
):
    return {
        "strategy_id": strategy_id,
        "name": "Free Shipping Over Threshold",
        "type": strategy_id,
        "parameters": {"threshold": threshold},
        "confidence": confidence,
        "reasoning": ["test"],
    }


# ─── _build_proposal helper ──────────────────────────────────────


class TestBuildProposal:

    def test_happy_path_yields_adapter_params(self):
        from engines.shipping_optimization.shipping_applier import (
            _build_proposal,
        )

        proposal = _build_proposal(_recommendation(), store=None)
        assert proposal is not None
        assert proposal["minimum_subtotal"] == 75.0
        assert proposal["title"] == "ShopAI: Free shipping over $75.00"
        assert proposal["ttl_days"] == 30
        assert proposal["adapter_params"]["minimum_subtotal"] == 75.0
        assert proposal["adapter_params"]["title"].startswith(
            "ShopAI:",
        )
        assert proposal["adapter_params"]["starts_at"].endswith("Z")
        assert proposal["adapter_params"]["ends_at"].endswith("Z")

    def test_wrong_strategy_returns_none(self):
        from engines.shipping_optimization.shipping_applier import (
            _build_proposal,
        )

        assert _build_proposal(
            _recommendation(strategy_id="flat_rate"), store=None,
        ) is None

    def test_zero_threshold_returns_none(self):
        from engines.shipping_optimization.shipping_applier import (
            _build_proposal,
        )

        assert _build_proposal(
            _recommendation(threshold=0.0), store=None,
        ) is None

    def test_sub_floor_confidence_returns_none(self):
        from engines.shipping_optimization.shipping_applier import (
            _build_proposal,
        )

        # Default floor is 0.55
        assert _build_proposal(
            _recommendation(confidence=0.30), store=None,
        ) is None

    def test_store_floor_override(self):
        from engines.shipping_optimization.shipping_applier import (
            _build_proposal,
        )

        # Bump floor so default 0.80 recommendation rejects.
        assert _build_proposal(
            _recommendation(confidence=0.80),
            store={"shipping_confidence_floor": 0.90},
        ) is None

    def test_custom_ttl(self):
        from engines.shipping_optimization.shipping_applier import (
            _build_proposal,
        )

        proposal = _build_proposal(
            _recommendation(),
            store={"free_shipping_ttl_days": 7},
        )
        assert proposal is not None
        assert proposal["ttl_days"] == 7

    def test_garbage_ttl_falls_back_to_default(self):
        from engines.shipping_optimization.shipping_applier import (
            _build_proposal,
        )

        proposal = _build_proposal(
            _recommendation(),
            store={"free_shipping_ttl_days": "many"},
        )
        assert proposal is not None
        assert proposal["ttl_days"] == 30

    def test_non_dict_recommendation_returns_none(self):
        from engines.shipping_optimization.shipping_applier import (
            _build_proposal,
        )

        assert _build_proposal(None, store=None) is None
        assert _build_proposal("garbage", store=None) is None


# ─── apply_shipping_strategy (direct path) ───────────────────────


class TestApplyShippingStrategy:

    def test_happy_path_calls_router(self):
        from engines.shipping_optimization import shipping_applier

        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.data = {
            "id": "gid://shopify/AutoDiscount/1",
            "title": "ShopAI: Free shipping over $75.00",
            "status": "ACTIVE",
            "starts_at": "2026-05-08T00:00:00Z",
            "ends_at": "2026-06-07T00:00:00Z",
        }
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            shipping_applier, "_get_router", return_value=fake_router,
        ):
            result = shipping_applier.apply_shipping_strategy(
                recommendation=_recommendation(),
                estimated_savings_monthly=250.0,
            )

        assert result is not None
        assert result["applied"] is True
        assert result["strategy_id"] == "free_over_threshold"
        assert result["threshold"] == 75.0
        assert result["discount_id"] == "gid://shopify/AutoDiscount/1"
        assert result["error"] is None
        fake_router.execute.assert_called_once()

    def test_wrong_strategy_returns_none(self):
        from engines.shipping_optimization import shipping_applier

        assert shipping_applier.apply_shipping_strategy(
            recommendation=_recommendation(strategy_id="calculated"),
            estimated_savings_monthly=100.0,
        ) is None

    def test_router_unavailable_returns_structured_skip(self):
        from engines.shipping_optimization import shipping_applier

        with patch.object(
            shipping_applier, "_get_router", return_value=None,
        ):
            result = shipping_applier.apply_shipping_strategy(
                recommendation=_recommendation(),
                estimated_savings_monthly=100.0,
            )
        assert result is not None
        assert result["applied"] is False
        assert result["error"] == "router_unavailable"
        assert result["discount_id"] == ""

    def test_adapter_failed_surfaces_error(self):
        from engines.shipping_optimization import shipping_applier

        fake_result = MagicMock()
        fake_result.ok = False
        fake_result.error = "title taken"
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            shipping_applier, "_get_router", return_value=fake_router,
        ):
            result = shipping_applier.apply_shipping_strategy(
                recommendation=_recommendation(),
                estimated_savings_monthly=50.0,
            )

        assert result is not None
        assert result["applied"] is False
        assert result["error"].startswith("adapter_failed:")
        assert "title taken" in result["error"]

    def test_adapter_raised_surfaces_error(self):
        from engines.shipping_optimization import shipping_applier

        fake_router = MagicMock()
        fake_router.execute = MagicMock(
            side_effect=RuntimeError("boom"),
        )

        with patch.object(
            shipping_applier, "_get_router", return_value=fake_router,
        ):
            result = shipping_applier.apply_shipping_strategy(
                recommendation=_recommendation(),
                estimated_savings_monthly=50.0,
            )

        assert result is not None
        assert result["applied"] is False
        assert result["error"].startswith("adapter_raised:")
        assert "boom" in result["error"]


# ─── enqueue_shipping_for_approval ───────────────────────────────


class TestEnqueueShippingForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.shipping_optimization.shipping_applier import (
            enqueue_shipping_for_approval,
        )

        result = enqueue_shipping_for_approval(
            recommendation=_recommendation(),
            estimated_savings_monthly=250.0,
            store={"free_shipping_ttl_days": 14},
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "$75.00" in result["narrative"]
        assert "14d window" in result["narrative"]
        assert result["params"]["threshold"] == 75.0
        assert result["params"]["ttl_days"] == 14

        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "shipping_optimization"
        assert action.action_type == "apply_shipping_strategy"
        assert action.capability == "SHOPIFY_CREATE_AUTOMATIC_FREE_SHIPPING"

    def test_wrong_strategy_returns_none(self, isolated_queue):
        from engines.shipping_optimization.shipping_applier import (
            enqueue_shipping_for_approval,
        )

        assert enqueue_shipping_for_approval(
            recommendation=_recommendation(strategy_id="flat_rate"),
            estimated_savings_monthly=50.0,
        ) is None
        assert isolated_queue.list_pending() == []

    def test_zero_threshold_returns_none(self, isolated_queue):
        from engines.shipping_optimization.shipping_applier import (
            enqueue_shipping_for_approval,
        )

        assert enqueue_shipping_for_approval(
            recommendation=_recommendation(threshold=0.0),
            estimated_savings_monthly=50.0,
        ) is None

    def test_sub_floor_confidence_returns_none(self, isolated_queue):
        from engines.shipping_optimization.shipping_applier import (
            enqueue_shipping_for_approval,
        )

        assert enqueue_shipping_for_approval(
            recommendation=_recommendation(confidence=0.30),
            estimated_savings_monthly=50.0,
        ) is None

    def test_queue_unavailable_returns_none(self, isolated_queue):
        from engines.shipping_optimization.shipping_applier import (
            enqueue_shipping_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_shipping_for_approval(
                recommendation=_recommendation(),
                estimated_savings_monthly=50.0,
            )
        assert result is None


# ─── flow integration ───────────────────────────────────────────


def _flow_input(
    *, apply_shipping_strategy=None, require_approval=None,
):
    data: dict = {
        "products": [
            {"id": "p1", "title": "Widget", "price": 50.0,
             "weight": 1.0},
        ],
        "origin_zip": "10001",
        "avg_order_value": 60.0,
        "monthly_orders": 500,
        "current_shipping_strategy": "flat_rate_5.99",
        "store": {"free_shipping_ttl_days": 14},
    }
    if apply_shipping_strategy is not None:
        data["apply_shipping_strategy"] = apply_shipping_strategy
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.shipping_optimization.flow import (
            ShippingOptimizationEngine,
        )

        with patch(
            "engines.shipping_optimization.flow.apply_shipping_strategy",
        ) as mock_apply, patch(
            "engines.shipping_optimization.flow.enqueue_shipping_for_approval",
        ) as mock_enqueue:
            output = ShippingOptimizationEngine().run(_flow_input())

        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["shipping_apply_result"] is None
            assert output["data"]["shipping_pending_action"] is None

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.shipping_optimization.flow import (
            ShippingOptimizationEngine,
        )

        stub = {
            "applied": True,
            "strategy_id": "free_over_threshold",
            "threshold": 75.0,
            "title": "ShopAI: Free shipping over $75.00",
            "starts_at": "2026-05-08T00:00:00Z",
            "ends_at": "2026-06-07T00:00:00Z",
            "discount_id": "gid://shopify/AutoDiscount/1",
            "error": None,
        }
        with patch(
            "engines.shipping_optimization.flow.apply_shipping_strategy",
            return_value=stub,
        ) as mock_apply, patch(
            "engines.shipping_optimization.flow.enqueue_shipping_for_approval",
        ) as mock_enqueue:
            output = ShippingOptimizationEngine().run(
                _flow_input(
                    apply_shipping_strategy=True,
                    require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_apply.assert_called_once()
            assert output["data"]["shipping_apply_result"] == stub
            assert output["data"]["shipping_pending_action"] is None

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.shipping_optimization.flow import (
            ShippingOptimizationEngine,
        )

        stub = {
            "pending_action_id": "appr_stub_1",
            "narrative": "shipping stub",
            "params": {},
        }
        with patch(
            "engines.shipping_optimization.flow.apply_shipping_strategy",
        ) as mock_apply, patch(
            "engines.shipping_optimization.flow.enqueue_shipping_for_approval",
            return_value=stub,
        ) as mock_enqueue:
            output = ShippingOptimizationEngine().run(
                _flow_input(
                    apply_shipping_strategy=True,
                    require_approval=True,
                ),
            )

        mock_apply.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["shipping_pending_action"] == stub
            assert output["data"]["shipping_apply_result"] is None
