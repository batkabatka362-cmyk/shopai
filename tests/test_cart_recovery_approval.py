"""Tests for the cart_recovery approval-queue wiring.

Pre-fix cart_recovery unconditionally minted a code on every
cycle whenever the SmartRouter was available — out of line
with the audit-driven opt-in pattern used by the other nine
writeback engines. This PR brings cart_recovery in line:

  * default OFF (no Shopify write without explicit opt-in)
  * direct mint via ``data.apply_recovery=True``
  * approval-queue path via
    ``data.apply_recovery=True + data.require_approval=True``

Coverage:
  1. ``enqueue_recovery_for_approval`` happy path
  2. Skip semantics: non-mintable incentive, zero / negative
     value, queue-unavailable
  3. flow integration — all three branches of Stage 4.5
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


# ─── enqueue_recovery_for_approval ───────────────────────────────


def _incentive(**overrides):
    base = {"type": "percentage", "value": 10}
    base.update(overrides)
    return base


def _customer(**overrides):
    base = {
        "id": "gid://shopify/Customer/123",
        "email": "buyer@example.com",
    }
    base.update(overrides)
    return base


class TestEnqueueRecoveryForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.cart_recovery.discount_minter import (
            enqueue_recovery_for_approval,
        )

        result = enqueue_recovery_for_approval(
            _incentive(value=15),
            _customer(),
            {"recovery_code_ttl_days": 5},
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "15% off" in result["narrative"]
        assert result["params"]["value_kind"] == "percentage"
        assert result["params"]["ttl_days"] == 5

        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "cart_recovery"
        assert action.action_type == "mint_cart_recovery_code"
        assert action.capability == "SHOPIFY_CREATE_DISCOUNT"
        assert action.status.value == "pending"

    def test_amount_incentive_emits_off_suffix(self, isolated_queue):
        from engines.cart_recovery.discount_minter import (
            enqueue_recovery_for_approval,
        )

        result = enqueue_recovery_for_approval(
            _incentive(type="amount", value=5),
            _customer(),
        )
        assert result is not None
        # "5 off" reads as "$5 off" — percentage suffix is "%".
        assert "5 off" in result["narrative"]
        assert "%" not in result["narrative"]

    def test_non_mintable_incentive_type_skipped(self, isolated_queue):
        from engines.cart_recovery.discount_minter import (
            enqueue_recovery_for_approval,
        )

        for bad_type in ["free_shipping", "bundle", "loyalty_points", "none"]:
            result = enqueue_recovery_for_approval(
                _incentive(type=bad_type),
                _customer(),
            )
            assert result is None, f"type={bad_type}"
        assert isolated_queue.list_pending() == []

    def test_zero_or_negative_value_skipped(self, isolated_queue):
        from engines.cart_recovery.discount_minter import (
            enqueue_recovery_for_approval,
        )

        for bad_val in [0, -5, "not-a-number"]:
            assert enqueue_recovery_for_approval(
                _incentive(value=bad_val), _customer(),
            ) is None, f"value={bad_val}"

    def test_queue_failure_does_not_crash(self, isolated_queue):
        from engines.cart_recovery.discount_minter import (
            enqueue_recovery_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_recovery_for_approval(
                _incentive(), _customer(),
            )
        assert result is None


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_recovery=None, require_approval=None):
    data: dict = {
        "cart": {
            "items": [{"product_id": "p1", "price": 50, "quantity": 1}],
            "total": 50,
            "customer_id": "gid://shopify/Customer/123",
        },
        "customer": {
            "id": "gid://shopify/Customer/123",
            "email": "buyer@example.com",
        },
        "store": {"avg_margin": 0.4},
    }
    if apply_recovery is not None:
        data["apply_recovery"] = apply_recovery
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        # Pre-fix this stage ran unconditionally — assert the new
        # safer default genuinely skips BOTH paths.
        from engines.cart_recovery.flow import CartRecoveryEngine

        with patch(
            "engines.cart_recovery.flow.mint_recovery_code",
        ) as mock_mint, patch(
            "engines.cart_recovery.flow.enqueue_recovery_for_approval",
        ) as mock_enqueue:
            output = CartRecoveryEngine().run(_flow_input())

        mock_mint.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["pending_action"] is None
            assert output["data"]["incentive"]["code"] == ""

    def test_apply_recovery_true_routes_to_direct_mint(
        self, isolated_queue,
    ):
        from engines.cart_recovery.flow import CartRecoveryEngine

        with patch(
            "engines.cart_recovery.flow.mint_recovery_code",
            return_value={
                "code": "RECOVER-X-1", "discount_id": "1",
                "ends_at": "2099-01-01", "applies_once": True,
            },
        ) as mock_mint, patch(
            "engines.cart_recovery.flow.enqueue_recovery_for_approval",
        ) as mock_enqueue:
            output = CartRecoveryEngine().run(
                _flow_input(apply_recovery=True, require_approval=False),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_mint.assert_called_once()
            assert output["data"]["incentive"]["code"] == "RECOVER-X-1"
            assert output["data"]["pending_action"] is None

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.cart_recovery.flow import CartRecoveryEngine

        stub = {
            "pending_action_id": "appr_stub_1",
            "narrative": "Cart recovery stub",
            "params": {},
        }
        with patch(
            "engines.cart_recovery.flow.mint_recovery_code",
        ) as mock_mint, patch(
            "engines.cart_recovery.flow.enqueue_recovery_for_approval",
            return_value=stub,
        ) as mock_enqueue:
            output = CartRecoveryEngine().run(
                _flow_input(apply_recovery=True, require_approval=True),
            )

        mock_mint.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["pending_action"] == stub
            assert output["data"]["incentive"]["code"] == ""
