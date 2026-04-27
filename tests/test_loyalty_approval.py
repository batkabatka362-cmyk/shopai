"""Tests for the loyalty approval-queue wiring.

Mirrors the discount_strategy approval tests at the loyalty
shape: per-customer reward enqueue rather than per-storewide
strategy. Coverage:

  1. ``enqueue_loyalty_for_approval`` happy path — proposal is
     parked and the returned dict carries the pending_action_id.
  2. Same upfront guardrails as ``mint_loyalty_code``:
     non-discount reward type / unparseable percentage skip
     without touching the queue.
  3. Approval-queue write failure returns None (best-effort).
  4. flow integration — ``data.apply_rewards=True`` +
     ``data.require_approval=True`` enqueues each customer's top
     discount reward and surfaces pending_actions in the engine
     output, leaving minted_codes empty.
  5. Default behaviour preserved — ``data.apply_rewards=True``
     with ``require_approval`` absent calls ``mint_loyalty_code``
     for each customer.
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


# ─── enqueue_loyalty_for_approval ───────────────────────────────


class TestEnqueueLoyaltyForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.loyalty.discount_minter import (
            enqueue_loyalty_for_approval,
        )

        result = enqueue_loyalty_for_approval(
            customer_id="gid://shopify/Customer/123",
            reward={
                "type": "discount", "reward": "10% off next order",
                "points_cost": 100,
            },
            program_config={"loyalty_code_ttl_days": 14},
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "10% off" in result["narrative"]
        assert "Customer/123" in result["narrative"]
        assert result["params"]["percentage"] == 10.0
        assert result["params"]["customer_id"] == "gid://shopify/Customer/123"
        assert result["params"]["ttl_days"] == 14
        # Persisted in the queue.
        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "loyalty"
        assert action.action_type == "mint_loyalty_code"
        assert action.capability == "SHOPIFY_CREATE_DISCOUNT"
        assert action.status.value == "pending"

    def test_non_discount_reward_skipped(self, isolated_queue):
        from engines.loyalty.discount_minter import (
            enqueue_loyalty_for_approval,
        )

        result = enqueue_loyalty_for_approval(
            customer_id="gid://shopify/Customer/123",
            reward={"type": "free_shipping", "reward": "free shipping"},
        )
        assert result is None
        assert isolated_queue.list_pending() == []

    def test_unparseable_percentage_skipped(self, isolated_queue):
        from engines.loyalty.discount_minter import (
            enqueue_loyalty_for_approval,
        )

        result = enqueue_loyalty_for_approval(
            customer_id="gid://shopify/Customer/123",
            reward={"type": "discount", "reward": "early access perk"},
        )
        assert result is None

    def test_queue_failure_does_not_crash(self, isolated_queue):
        from engines.loyalty.discount_minter import (
            enqueue_loyalty_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_loyalty_for_approval(
                customer_id="gid://shopify/Customer/123",
                reward={"type": "discount", "reward": "10% off"},
            )
        assert result is None


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_rewards: bool, require_approval: bool):
    """Build a loyalty engine input. Reward generation is patched
    in the test bodies below — the input only needs to make it
    past the upstream stages so we reach stage 5b."""
    return {
        "status": "ok",
        "data": {
            "customers": [
                {
                    "id": "gid://shopify/Customer/1",
                    "lifetime_value": 800.0,
                    "order_count": 12,
                    "last_order_days_ago": 10,
                },
            ],
            "program_config": {
                "tier_thresholds": {
                    "Bronze": 0, "Silver": 500, "Gold": 1500,
                },
                "reward_catalog": [
                    {"type": "discount", "reward": "10% off next order",
                     "points_cost": 100, "tier": "Silver"},
                ],
                "loyalty_code_ttl_days": 30,
            },
            "apply_rewards": apply_rewards,
            "require_approval": require_approval,
        },
        "meta": {},
        "error": None,
    }


def _stub_recommendations():
    """Deterministic recommendations the writeback stage will
    consume regardless of upstream points/tier behaviour."""
    return [
        {
            "customer_id": "gid://shopify/Customer/1",
            "recommended_rewards": [
                {
                    "type": "discount",
                    "reward": "10% off next order",
                    "points_cost": 100,
                    "tier": "Silver",
                },
            ],
            "reason": "Silver tier auto-reward",
        },
    ]


class TestFlowApprovalIntegration:

    def test_require_approval_true_enqueues_skips_mint(
        self, isolated_queue,
    ):
        from engines.loyalty.flow import LoyaltyEngine

        # Stub the upstream recommender so the writeback stage is
        # the unit under test — we don't depend on points /
        # tier-manager behaviour producing an above-floor reward.
        with patch(
            "engines.loyalty.flow.recommend_rewards",
            return_value={
                "status": "success",
                "recommendations": _stub_recommendations(),
            },
        ), patch(
            "engines.loyalty.flow.mint_loyalty_code",
        ) as mock_mint, patch(
            "engines.loyalty.flow.enqueue_loyalty_for_approval",
            return_value={
                "pending_action_id": "appr_stub",
                "narrative": "stub",
                "params": {},
            },
        ) as mock_enqueue:
            output = LoyaltyEngine().run(
                _flow_input(apply_rewards=True, require_approval=True),
            )

        assert output["status"] == "success"
        # Direct mint MUST NOT be called when approval is required.
        mock_mint.assert_not_called()
        # Approval path was called for the stubbed customer.
        assert mock_enqueue.called
        # Engine output surfaces pending_actions, leaves minted_codes empty.
        assert output["data"]["pending_actions"]
        assert output["data"]["pending_actions"][0]["pending_action_id"] == "appr_stub"
        assert output["data"]["minted_codes"] == []

    def test_require_approval_false_falls_back_to_direct_mint(
        self, isolated_queue,
    ):
        from engines.loyalty.flow import LoyaltyEngine

        with patch(
            "engines.loyalty.flow.recommend_rewards",
            return_value={
                "status": "success",
                "recommendations": _stub_recommendations(),
            },
        ), patch(
            "engines.loyalty.flow.mint_loyalty_code",
            return_value={
                "code": "LOYALTY-XX", "discount_id": "1",
                "ends_at": "2099-01-01", "applies_once": True,
            },
        ) as mock_mint, patch(
            "engines.loyalty.flow.enqueue_loyalty_for_approval",
        ) as mock_enqueue:
            output = LoyaltyEngine().run(
                _flow_input(apply_rewards=True, require_approval=False),
            )

        assert output["status"] == "success"
        mock_enqueue.assert_not_called()
        assert mock_mint.called
        assert output["data"]["minted_codes"]
        assert output["data"]["minted_codes"][0]["code"] == "LOYALTY-XX"
        assert output["data"]["pending_actions"] == []

    def test_apply_rewards_false_skips_both_paths(self, isolated_queue):
        from engines.loyalty.flow import LoyaltyEngine

        with patch(
            "engines.loyalty.flow.mint_loyalty_code",
        ) as mock_mint, patch(
            "engines.loyalty.flow.enqueue_loyalty_for_approval",
        ) as mock_enqueue:
            output = LoyaltyEngine().run(
                _flow_input(apply_rewards=False, require_approval=True),
            )

        assert output["status"] == "success"
        mock_mint.assert_not_called()
        mock_enqueue.assert_not_called()
        assert output["data"]["minted_codes"] == []
        assert output["data"]["pending_actions"] == []
