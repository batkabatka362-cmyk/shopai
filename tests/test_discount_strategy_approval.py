"""Tests for the discount_strategy approval-queue wiring.

Coverage:
  1. ``enqueue_strategy_for_approval`` happy path — proposal is
     parked in core.approval and the returned dict carries the
     pending_action_id.
  2. Same upfront guardrails as ``mint_strategy_code``: non-
     percentage type / non-positive depth / high cannibalization
     risk / confidence below floor all return None without
     touching the queue.
  3. flow integration — ``data.apply_discount=True`` +
     ``data.require_approval=True`` enqueues; the engine output
     surfaces ``pending_action`` and skips ``minted_code``.
  4. Default behaviour preserved — ``data.apply_discount=True``
     with ``require_approval`` absent still calls
     ``mint_strategy_code`` (the legacy direct-mint path).
  5. Approval-queue write failures do NOT crash the engine.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


# ─── enqueue_strategy_for_approval ──────────────────────────────


@pytest.fixture
def isolated_queue(tmp_path: Path, monkeypatch):
    """Swap the approval-queue singleton for a temp-DB instance."""
    from core.approval import queue as q
    from core.approval.queue import ApprovalQueue

    fresh = ApprovalQueue(db_path=tmp_path / "approval.db")
    monkeypatch.setattr(q, "_INSTANCE", fresh)
    yield fresh
    fresh._conn.close()


class TestEnqueueStrategyForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.discount_strategy.discount_minter import (
            enqueue_strategy_for_approval,
        )

        result = enqueue_strategy_for_approval(
            strategy={
                "type": "percentage_off",
                "depth_pct": 0.15,
                "target_audience": "all",
                "duration_hours": 48,
            },
            cannibalization_risk="low",
            confidence=0.78,
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "15% off" in result["narrative"]
        assert result["params"]["percentage"] == 15.0
        assert result["params"]["audience"] == "all"
        # Action actually persisted.
        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "discount_strategy"
        assert action.action_type == "mint_strategy_code"
        assert action.capability == "SHOPIFY_CREATE_DISCOUNT"
        assert action.status.value == "pending"
        assert action.confidence == 0.78

    def test_non_percentage_type_skipped(self, isolated_queue):
        from engines.discount_strategy.discount_minter import (
            enqueue_strategy_for_approval,
        )

        result = enqueue_strategy_for_approval(
            strategy={
                "type": "bogo", "depth_pct": 0.5,
                "target_audience": "vip",
            },
        )
        assert result is None
        # Nothing landed in the queue either.
        assert isolated_queue.list_pending() == []

    def test_high_cannibalization_risk_skipped(self, isolated_queue):
        from engines.discount_strategy.discount_minter import (
            enqueue_strategy_for_approval,
        )

        result = enqueue_strategy_for_approval(
            strategy={
                "type": "percentage_off", "depth_pct": 0.20,
                "target_audience": "all",
            },
            cannibalization_risk="high",
        )
        assert result is None

    def test_below_confidence_floor_skipped(self, isolated_queue):
        from engines.discount_strategy.discount_minter import (
            enqueue_strategy_for_approval,
        )

        result = enqueue_strategy_for_approval(
            strategy={
                "type": "percentage_off", "depth_pct": 0.10,
                "target_audience": "all",
            },
            confidence=0.3,
            min_confidence=0.5,
        )
        assert result is None

    def test_zero_or_negative_depth_skipped(self, isolated_queue):
        from engines.discount_strategy.discount_minter import (
            enqueue_strategy_for_approval,
        )

        for bad_depth in [0, -0.1, 0.0]:
            result = enqueue_strategy_for_approval(
                strategy={
                    "type": "percentage_off", "depth_pct": bad_depth,
                    "target_audience": "all",
                },
            )
            assert result is None, f"depth_pct={bad_depth}"

    def test_queue_failure_does_not_crash(self, isolated_queue):
        from engines.discount_strategy.discount_minter import (
            enqueue_strategy_for_approval,
        )

        # The minter does ``from core.approval import
        # get_approval_queue`` so the symbol is looked up on the
        # package's ``__init__`` namespace at call time.
        # Patching ``core.approval.queue.get_approval_queue``
        # would not catch this — the name in the parent package
        # was bound at re-export time.
        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_strategy_for_approval(
                strategy={
                    "type": "percentage_off", "depth_pct": 0.15,
                    "target_audience": "all",
                },
            )
        assert result is None


# ─── flow integration ───────────────────────────────────────────


def _flow_input(*, apply_discount: bool, require_approval: bool):
    """Build a discount_strategy engine input that exercises the
    full happy-path pipeline so we reach the writeback stage."""
    return {
        "status": "ok",
        "data": {
            "products": [
                {
                    "id": "p1",
                    "title": "Widget",
                    "price": 50.0,
                    "cost": 25.0,
                    "daily_sales": 5,
                },
            ],
            "goal": "boost_revenue",
            "inventory_days": 60,
            "customer_segments": [],
            "apply_discount": apply_discount,
            "require_approval": require_approval,
        },
        "meta": {},
        "error": None,
    }


class TestFlowApprovalIntegration:

    def test_require_approval_true_enqueues_skips_mint(
        self, isolated_queue,
    ):
        from engines.discount_strategy.flow import DiscountStrategyEngine

        # Patch enqueue with a deterministic stub so the test
        # doesn't depend on the full pipeline producing a
        # mint-eligible (low-risk + above-floor) strategy. The
        # routing is what's under test here, not the upstream
        # math.
        stub_action = {
            "pending_action_id": "appr_stub_123",
            "narrative": "stub",
            "params": {},
        }
        with patch(
            "engines.discount_strategy.flow.mint_strategy_code",
        ) as mock_mint, patch(
            "engines.discount_strategy.flow.enqueue_strategy_for_approval",
            return_value=stub_action,
        ) as mock_enqueue:
            output = DiscountStrategyEngine().run(
                _flow_input(apply_discount=True, require_approval=True),
            )

        assert output["status"] == "success"
        # Direct mint MUST NOT be called when approval is required.
        mock_mint.assert_not_called()
        # Approval path WAS called.
        mock_enqueue.assert_called_once()
        # Pending action surfaced in output, mint stays None.
        assert output["data"]["pending_action"] == stub_action
        assert output["data"]["minted_code"] is None

    def test_require_approval_false_falls_back_to_direct_mint(
        self, isolated_queue,
    ):
        from engines.discount_strategy.flow import DiscountStrategyEngine

        with patch(
            "engines.discount_strategy.flow.mint_strategy_code",
            return_value={"code": "PROMO-XX", "discount_id": "1"},
        ) as mock_mint, patch(
            "engines.discount_strategy.flow.enqueue_strategy_for_approval",
        ) as mock_enqueue:
            output = DiscountStrategyEngine().run(
                _flow_input(apply_discount=True, require_approval=False),
            )

        assert output["status"] == "success"
        # Direct mint called; approval queue NOT consulted.
        mock_mint.assert_called_once()
        mock_enqueue.assert_not_called()
        assert output["data"]["minted_code"] == {
            "code": "PROMO-XX", "discount_id": "1",
        }
        assert output["data"]["pending_action"] is None

    def test_apply_discount_false_skips_both_paths(self, isolated_queue):
        from engines.discount_strategy.flow import DiscountStrategyEngine

        with patch(
            "engines.discount_strategy.flow.mint_strategy_code",
        ) as mock_mint, patch(
            "engines.discount_strategy.flow.enqueue_strategy_for_approval",
        ) as mock_enqueue:
            output = DiscountStrategyEngine().run(
                _flow_input(apply_discount=False, require_approval=True),
            )

        assert output["status"] == "success"
        # Both paths skipped: opt-in flag wins over approval flag.
        mock_mint.assert_not_called()
        mock_enqueue.assert_not_called()
        assert output["data"]["minted_code"] is None
        assert output["data"]["pending_action"] is None
