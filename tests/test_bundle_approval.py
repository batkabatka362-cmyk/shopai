"""Tests for the bundle engine's bundle-product writeback.

The bundle engine emits ``{bundles, best_bundle,
cannibalization_risk}``. Pre-fix the proposal was advisory — the
merchant had to create a Shopify product manually with the right
title + tags + body. The applier creates a DRAFT product matching
the proposal so the merchant only has to wire components and
publish.

Coverage:
  1. ``_pair_components`` matches ids and titles by index, drops
     blanks, handles length-mismatch.
  2. ``_build_title`` / ``_build_body`` formatting.
  3. ``_is_blocked_by_cannibalization`` matches bundle_id and
     gates on ``reconsider_bundle`` recommendation.
  4. ``_build_proposal`` guardrails (no bundle, <2 components,
     zero savings, blocked cannibalization).
  5. ``apply_bundle_product`` happy + router unavailable +
     adapter failed + adapter raised.
  6. ``enqueue_bundle_for_approval`` happy + skip + queue
     unavailable.
  7. Flow integration — three branches of Stage 6.5.
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


def _best_bundle(
    *,
    bundle_id="b1",
    product_ids=None,
    product_titles=None,
    savings_pct=15.0,
    bundle_price=29.99,
    estimated_uplift=2.5,
):
    return {
        "bundle_id": bundle_id,
        "product_ids": product_ids or [
            "gid://shopify/Product/1",
            "gid://shopify/Product/2",
        ],
        "product_titles": product_titles or ["Widget", "Gadget"],
        "products": product_titles or ["Widget", "Gadget"],
        "bundle_price": bundle_price,
        "savings_pct": savings_pct,
        "estimated_uplift": estimated_uplift,
        "margin": 0.30,
    }


# ─── Helper functions ──────────────────────────────────────────


class TestPairComponents:

    def test_happy_path(self):
        from engines.bundle.bundle_applier import _pair_components
        pairs = _pair_components(
            ["gid://shopify/Product/1", "gid://shopify/Product/2"],
            ["Widget", "Gadget"],
        )
        assert pairs == [
            {"id": "gid://shopify/Product/1", "title": "Widget"},
            {"id": "gid://shopify/Product/2", "title": "Gadget"},
        ]

    def test_drops_blank_ids(self):
        from engines.bundle.bundle_applier import _pair_components
        pairs = _pair_components(
            ["", "gid://shopify/Product/2"], ["X", "Y"],
        )
        assert pairs == [
            {"id": "gid://shopify/Product/2", "title": "Y"},
        ]

    def test_falls_back_when_title_blank(self):
        from engines.bundle.bundle_applier import _pair_components
        pairs = _pair_components(
            ["gid://shopify/Product/12345"], [""],
        )
        assert pairs[0]["id"] == "gid://shopify/Product/12345"
        assert pairs[0]["title"] == "Product 12345"

    def test_ids_longer_than_titles(self):
        from engines.bundle.bundle_applier import _pair_components
        pairs = _pair_components(
            ["gid://shopify/Product/1", "gid://shopify/Product/2"],
            ["Widget"],
        )
        assert len(pairs) == 2
        assert pairs[0]["title"] == "Widget"
        assert pairs[1]["title"] == "Product 2"


class TestBuildTitle:

    def test_two_components(self):
        from engines.bundle.bundle_applier import _build_title
        assert _build_title([
            {"id": "1", "title": "A"},
            {"id": "2", "title": "B"},
        ]) == "Bundle: A + B"

    def test_three_components(self):
        from engines.bundle.bundle_applier import _build_title
        assert _build_title([
            {"id": "1", "title": "A"},
            {"id": "2", "title": "B"},
            {"id": "3", "title": "C"},
        ]) == "Bundle: A + B + C"

    def test_four_components_truncates(self):
        from engines.bundle.bundle_applier import _build_title
        title = _build_title([
            {"id": str(i), "title": f"P{i}"} for i in range(5)
        ])
        assert title == "Bundle: P0 + P1 + P2 + 2 more"


class TestBuildBody:

    def test_includes_all_components_and_savings(self):
        from engines.bundle.bundle_applier import _build_body
        body = _build_body(
            [{"id": "1", "title": "Widget"},
             {"id": "2", "title": "Gadget"}],
            savings_pct=15.0, bundle_price=29.99,
        )
        assert "<li>Widget</li>" in body
        assert "<li>Gadget</li>" in body
        assert "15% off" in body
        assert "$29.99" in body
        assert "2 products" in body


class TestIsBlockedByCannibalization:

    def test_reconsider_blocks(self):
        from engines.bundle.bundle_applier import (
            _is_blocked_by_cannibalization,
        )
        assert _is_blocked_by_cannibalization(
            {"bundle_id": "b1"},
            [{"bundle_id": "b1",
              "recommendation": "reconsider_bundle"}],
        ) is True

    def test_safe_to_launch_allows(self):
        from engines.bundle.bundle_applier import (
            _is_blocked_by_cannibalization,
        )
        assert _is_blocked_by_cannibalization(
            {"bundle_id": "b1"},
            [{"bundle_id": "b1",
              "recommendation": "safe_to_launch"}],
        ) is False

    def test_no_match_allows(self):
        from engines.bundle.bundle_applier import (
            _is_blocked_by_cannibalization,
        )
        # No entry for this bundle — default-allow.
        assert _is_blocked_by_cannibalization(
            {"bundle_id": "b1"},
            [{"bundle_id": "other",
              "recommendation": "reconsider_bundle"}],
        ) is False

    def test_missing_bundle_id_allows(self):
        from engines.bundle.bundle_applier import (
            _is_blocked_by_cannibalization,
        )
        assert _is_blocked_by_cannibalization({}, []) is False


# ─── _build_proposal ───────────────────────────────────────────


class TestBuildProposal:

    def test_happy_path(self):
        from engines.bundle.bundle_applier import _build_proposal
        proposal = _build_proposal(_best_bundle(), [], None)
        assert proposal is not None
        assert proposal["title"] == "Bundle: Widget + Gadget"
        assert len(proposal["components"]) == 2
        assert proposal["adapter_params"]["status"] == "DRAFT"
        assert proposal["adapter_params"]["product_type"] == "Bundle"
        assert "shopai-bundle" in proposal["adapter_params"]["tags"]
        # Component-id tags present.
        component_tags = [
            t for t in proposal["adapter_params"]["tags"]
            if t.startswith("shopai-bundle-component-")
        ]
        assert len(component_tags) == 2

    def test_no_bundle_returns_none(self):
        from engines.bundle.bundle_applier import _build_proposal
        assert _build_proposal(None, [], None) is None
        assert _build_proposal({}, [], None) is None

    def test_single_component_returns_none(self):
        from engines.bundle.bundle_applier import _build_proposal
        assert _build_proposal(
            _best_bundle(
                product_ids=["gid://shopify/Product/1"],
                product_titles=["Solo"],
            ), [], None,
        ) is None

    def test_zero_savings_returns_none(self):
        from engines.bundle.bundle_applier import _build_proposal
        assert _build_proposal(
            _best_bundle(savings_pct=0), [], None,
        ) is None

    def test_blocked_cannibalization_returns_none(self):
        from engines.bundle.bundle_applier import _build_proposal
        assert _build_proposal(
            _best_bundle(bundle_id="b1"),
            [{"bundle_id": "b1",
              "recommendation": "reconsider_bundle"}],
            None,
        ) is None


# ─── apply_bundle_product (direct path) ────────────────────────


class TestApplyBundleProduct:

    def test_happy_path_calls_router(self):
        from engines.bundle import bundle_applier

        fake_result = MagicMock()
        fake_result.ok = True
        fake_result.data = {
            "product": {
                "id": "gid://shopify/Product/999",
                "title": "Bundle: Widget + Gadget",
                "status": "DRAFT",
            },
        }
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            bundle_applier, "_get_router", return_value=fake_router,
        ):
            result = bundle_applier.apply_bundle_product(
                best_bundle=_best_bundle(),
                cannibalization_risk=[],
            )

        assert result is not None
        assert result["applied"] is True
        assert result["bundle_product_id"] == (
            "gid://shopify/Product/999"
        )
        assert result["status"] == "DRAFT"
        assert result["savings_pct"] == 15.0
        assert result["error"] is None
        # Adapter received product_type=Bundle.
        payload = fake_router.execute.call_args[0][1]
        assert payload["product_type"] == "Bundle"
        assert payload["status"] == "DRAFT"

    def test_no_bundle_returns_none(self):
        from engines.bundle import bundle_applier
        assert bundle_applier.apply_bundle_product(
            best_bundle=None, cannibalization_risk=[],
        ) is None

    def test_router_unavailable_returns_structured_skip(self):
        from engines.bundle import bundle_applier

        with patch.object(
            bundle_applier, "_get_router", return_value=None,
        ):
            result = bundle_applier.apply_bundle_product(
                best_bundle=_best_bundle(),
                cannibalization_risk=[],
            )
        assert result is not None
        assert result["applied"] is False
        assert result["error"] == "router_unavailable"

    def test_adapter_failed_surfaces_error(self):
        from engines.bundle import bundle_applier

        fake_result = MagicMock()
        fake_result.ok = False
        fake_result.error = "title taken"
        fake_router = MagicMock()
        fake_router.execute = MagicMock(return_value=fake_result)

        with patch.object(
            bundle_applier, "_get_router", return_value=fake_router,
        ):
            result = bundle_applier.apply_bundle_product(
                best_bundle=_best_bundle(),
                cannibalization_risk=[],
            )

        assert result["applied"] is False
        assert result["error"].startswith("adapter_failed:")
        assert "title taken" in result["error"]

    def test_adapter_raised_surfaces_error(self):
        from engines.bundle import bundle_applier

        fake_router = MagicMock()
        fake_router.execute = MagicMock(
            side_effect=RuntimeError("boom"),
        )

        with patch.object(
            bundle_applier, "_get_router", return_value=fake_router,
        ):
            result = bundle_applier.apply_bundle_product(
                best_bundle=_best_bundle(),
                cannibalization_risk=[],
            )

        assert result["applied"] is False
        assert result["error"].startswith("adapter_raised:")
        assert "boom" in result["error"]


# ─── enqueue_bundle_for_approval ──────────────────────────────


class TestEnqueueBundleForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.bundle.bundle_applier import (
            enqueue_bundle_for_approval,
        )

        result = enqueue_bundle_for_approval(
            best_bundle=_best_bundle(),
            cannibalization_risk=[],
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "Bundle: Widget + Gadget" in result["narrative"]
        assert "2 components" in result["narrative"]
        assert "15% off" in result["narrative"]
        assert result["params"]["title"] == "Bundle: Widget + Gadget"

        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "bundle"
        assert action.action_type == "apply_bundle_product"
        assert action.capability == "SHOPIFY_CREATE_PRODUCT"

    def test_no_bundle_returns_none(self, isolated_queue):
        from engines.bundle.bundle_applier import (
            enqueue_bundle_for_approval,
        )
        assert enqueue_bundle_for_approval(
            best_bundle=None, cannibalization_risk=[],
        ) is None
        assert isolated_queue.list_pending() == []

    def test_single_component_returns_none(self, isolated_queue):
        from engines.bundle.bundle_applier import (
            enqueue_bundle_for_approval,
        )
        assert enqueue_bundle_for_approval(
            best_bundle=_best_bundle(
                product_ids=["gid://shopify/Product/1"],
                product_titles=["Solo"],
            ),
            cannibalization_risk=[],
        ) is None

    def test_blocked_cannibalization_returns_none(
        self, isolated_queue,
    ):
        from engines.bundle.bundle_applier import (
            enqueue_bundle_for_approval,
        )
        assert enqueue_bundle_for_approval(
            best_bundle=_best_bundle(bundle_id="b1"),
            cannibalization_risk=[{
                "bundle_id": "b1",
                "recommendation": "reconsider_bundle",
            }],
        ) is None

    def test_queue_unavailable_returns_none(self, isolated_queue):
        from engines.bundle.bundle_applier import (
            enqueue_bundle_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_bundle_for_approval(
                best_bundle=_best_bundle(),
                cannibalization_risk=[],
            )
        assert result is None


# ─── Flow integration ──────────────────────────────────────────


def _flow_input(*, apply_bundle=None, require_approval=None):
    data: dict = {
        "products": [
            {"id": "gid://shopify/Product/1", "title": "Widget",
             "price": 20.0},
            {"id": "gid://shopify/Product/2", "title": "Gadget",
             "price": 15.0},
        ],
        "orders": [
            {"line_items": [
                {"product_id": "gid://shopify/Product/1"},
                {"product_id": "gid://shopify/Product/2"},
            ]},
        ] * 5,
        "pricing_data": {},
        "constraints": {},
    }
    if apply_bundle is not None:
        data["apply_bundle"] = apply_bundle
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.bundle.flow import BundleEngine

        with patch(
            "engines.bundle.flow.apply_bundle_product",
        ) as mock_apply, patch(
            "engines.bundle.flow.enqueue_bundle_for_approval",
        ) as mock_enqueue:
            output = BundleEngine().run(_flow_input())

        mock_apply.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["bundle_apply_result"] is None
            assert output["data"]["bundle_pending_action"] is None

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.bundle.flow import BundleEngine

        stub = {
            "applied": True,
            "bundle_product_id": "gid://shopify/Product/999",
            "title": "Bundle: Widget + Gadget",
            "components": [],
            "savings_pct": 15.0,
            "status": "DRAFT",
            "error": None,
        }
        with patch(
            "engines.bundle.flow.apply_bundle_product",
            return_value=stub,
        ) as mock_apply, patch(
            "engines.bundle.flow.enqueue_bundle_for_approval",
        ) as mock_enqueue:
            output = BundleEngine().run(
                _flow_input(
                    apply_bundle=True, require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_apply.assert_called_once()
            assert output["data"]["bundle_apply_result"] == stub
            assert output["data"]["bundle_pending_action"] is None

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.bundle.flow import BundleEngine

        stub = {
            "pending_action_id": "appr_stub_1",
            "narrative": "bundle stub",
            "params": {},
        }
        with patch(
            "engines.bundle.flow.apply_bundle_product",
        ) as mock_apply, patch(
            "engines.bundle.flow.enqueue_bundle_for_approval",
            return_value=stub,
        ) as mock_enqueue:
            output = BundleEngine().run(
                _flow_input(
                    apply_bundle=True, require_approval=True,
                ),
            )

        mock_apply.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["bundle_pending_action"] == stub
            assert output["data"]["bundle_apply_result"] is None
