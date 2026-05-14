"""Tests for the wholesale_b2b approval-queue wiring (1C #5).

The engine's ``volume_discounts`` output carries per-line-item
discount percentages calculated against the merchant's pricing
tiers. The new applier picks the best ``discount_pct`` across
the order and mints one Shopify discount code per order — same
pattern as cart_recovery's per-customer mint, scoped to a
single wholesale order.

Coverage:
  1. ``_best_discount`` picks the largest pct across line items.
  2. ``mint_wholesale_code`` happy path, missing customer_id,
     all-zero discount short-circuit.
  3. ``enqueue_wholesale_for_approval`` mirrors above + queue-
     unavailable fallback.
  4. flow integration — three branches of Stage 4.5.
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


# ─── _best_discount helper ─────────────────────────────────────


class TestBestDiscount:

    def test_picks_largest(self):
        from engines.wholesale_b2b.discount_minter import _best_discount
        assert _best_discount([
            {"product_id": "p1", "discount_pct": 5},
            {"product_id": "p2", "discount_pct": 12},
            {"product_id": "p3", "discount_pct": 8},
        ]) == 12.0

    def test_empty_returns_none(self):
        from engines.wholesale_b2b.discount_minter import _best_discount
        assert _best_discount([]) is None

    def test_all_zero_returns_zero(self):
        from engines.wholesale_b2b.discount_minter import _best_discount
        assert _best_discount([
            {"product_id": "p1", "discount_pct": 0},
        ]) == 0.0

    def test_non_numeric_pct_ignored(self):
        from engines.wholesale_b2b.discount_minter import _best_discount
        assert _best_discount([
            {"product_id": "p1", "discount_pct": "garbage"},
            {"product_id": "p2", "discount_pct": 7},
        ]) == 7.0


# ─── mint_wholesale_code (direct path) ─────────────────────────


class TestMintWholesaleCode:

    def test_happy_path_routes_to_shared_helper(self):
        from engines.wholesale_b2b import discount_minter

        captured = {}

        def _stub_mint(**kwargs):
            captured.update(kwargs)
            return {
                "code": "WHOLESALE-CUSTACME-1234",
                "discount_id": "gid://shopify/Discount/1",
                "ends_at": "2099-01-01",
                "applies_once": True,
            }

        with patch.object(
            discount_minter, "_mint", side_effect=_stub_mint,
        ):
            result = discount_minter.mint_wholesale_code(
                order={"customer_id": "cust_acme", "total": 1000},
                volume_discounts=[
                    {"product_id": "p1", "discount_pct": 5},
                    {"product_id": "p2", "discount_pct": 12},
                ],
                store={"wholesale_code_ttl_days": 14},
            )

        assert result is not None
        assert result["code"] == "WHOLESALE-CUSTACME-1234"
        # Shared mint called with the right shape.
        assert captured["code_prefix"] == "WHOLESALE"
        assert captured["value"] == 12.0
        assert captured["value_kind"] == "percentage"
        assert captured["ttl_days"] == 14

    def test_no_customer_id_returns_none(self):
        from engines.wholesale_b2b import discount_minter

        result = discount_minter.mint_wholesale_code(
            order={},  # no customer_id
            volume_discounts=[
                {"product_id": "p1", "discount_pct": 10},
            ],
        )
        assert result is None

    def test_zero_best_discount_returns_none(self):
        from engines.wholesale_b2b import discount_minter

        result = discount_minter.mint_wholesale_code(
            order={"customer_id": "cust_acme"},
            volume_discounts=[
                {"product_id": "p1", "discount_pct": 0},
            ],
        )
        assert result is None

    def test_empty_volume_discounts_returns_none(self):
        from engines.wholesale_b2b import discount_minter

        result = discount_minter.mint_wholesale_code(
            order={"customer_id": "cust_acme"},
            volume_discounts=[],
        )
        assert result is None


# ─── enqueue_wholesale_for_approval ─────────────────────────────


class TestEnqueueWholesaleForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.wholesale_b2b.discount_minter import (
            enqueue_wholesale_for_approval,
        )

        result = enqueue_wholesale_for_approval(
            order={"customer_id": "cust_acme", "total": 1500},
            volume_discounts=[
                {"product_id": "p1", "discount_pct": 8},
                {"product_id": "p2", "discount_pct": 15},
            ],
            store={"wholesale_code_ttl_days": 30},
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "15% off" in result["narrative"]
        assert "$1500" in result["narrative"]
        assert result["params"]["value"] == 15.0
        assert result["params"]["ttl_days"] == 30

        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "wholesale_b2b"
        assert action.action_type == "mint_wholesale_code"
        assert action.capability == "SHOPIFY_CREATE_DISCOUNT"

    def test_no_customer_id_returns_none(self, isolated_queue):
        from engines.wholesale_b2b.discount_minter import (
            enqueue_wholesale_for_approval,
        )

        assert enqueue_wholesale_for_approval(
            order={},
            volume_discounts=[
                {"product_id": "p1", "discount_pct": 10},
            ],
        ) is None
        assert isolated_queue.list_pending() == []

    def test_zero_best_discount_returns_none(self, isolated_queue):
        from engines.wholesale_b2b.discount_minter import (
            enqueue_wholesale_for_approval,
        )

        assert enqueue_wholesale_for_approval(
            order={"customer_id": "cust_acme"},
            volume_discounts=[
                {"product_id": "p1", "discount_pct": 0},
            ],
        ) is None

    def test_queue_unavailable_returns_none(self, isolated_queue):
        from engines.wholesale_b2b.discount_minter import (
            enqueue_wholesale_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_wholesale_for_approval(
                order={"customer_id": "cust_acme"},
                volume_discounts=[
                    {"product_id": "p1", "discount_pct": 10},
                ],
            )
        assert result is None


# ─── flow integration ───────────────────────────────────────────


def _flow_input(
    *, apply_wholesale_discount=None, require_approval=None,
):
    data: dict = {
        "products": [
            {"id": "p1", "title": "Widget", "price": 50.0},
        ],
        "accounts": [],
        "pricing_config": {
            "tiers": [
                {"name": "bronze", "min_quantity": 10,
                 "discount_pct": 5},
                {"name": "silver", "min_quantity": 50,
                 "discount_pct": 12},
            ],
        },
        "order": {
            "customer_id": "cust_acme",
            "total": 1500,
            "items": [
                {"product_id": "p1", "quantity": 60},
            ],
        },
        "store": {"wholesale_code_ttl_days": 14},
    }
    if apply_wholesale_discount is not None:
        data["apply_wholesale_discount"] = apply_wholesale_discount
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.wholesale_b2b.flow import WholesaleB2bEngine

        with patch(
            "engines.wholesale_b2b.flow.mint_wholesale_code",
        ) as mock_mint, patch(
            "engines.wholesale_b2b.flow.enqueue_wholesale_for_approval",
        ) as mock_enqueue:
            output = WholesaleB2bEngine().run(_flow_input())

        mock_mint.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["minted_code"] is None
            assert output["data"]["pending_action"] is None

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.wholesale_b2b.flow import WholesaleB2bEngine

        with patch(
            "engines.wholesale_b2b.flow.mint_wholesale_code",
            return_value={
                "code": "WHOLESALE-XX",
                "discount_id": "1", "ends_at": "2099",
                "applies_once": True,
            },
        ) as mock_mint, patch(
            "engines.wholesale_b2b.flow.enqueue_wholesale_for_approval",
        ) as mock_enqueue:
            output = WholesaleB2bEngine().run(
                _flow_input(
                    apply_wholesale_discount=True,
                    require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_mint.assert_called_once()
            assert output["data"]["minted_code"]["code"] == "WHOLESALE-XX"
            assert output["data"]["pending_action"] is None

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.wholesale_b2b.flow import WholesaleB2bEngine

        stub = {
            "pending_action_id": "appr_stub_1",
            "narrative": "wholesale stub",
            "params": {},
        }
        with patch(
            "engines.wholesale_b2b.flow.mint_wholesale_code",
        ) as mock_mint, patch(
            "engines.wholesale_b2b.flow.enqueue_wholesale_for_approval",
            return_value=stub,
        ) as mock_enqueue:
            output = WholesaleB2bEngine().run(
                _flow_input(
                    apply_wholesale_discount=True,
                    require_approval=True,
                ),
            )

        mock_mint.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["pending_action"] == stub
            assert output["data"]["minted_code"] is None
