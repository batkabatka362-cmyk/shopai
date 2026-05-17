"""Tests for the v2 guardrail rollout across 5 discount minters.

Loyalty (PR #245) was the reference. PR #247 extracted helpers.
This PR (per-engine wiring) opts in cart_recovery,
browse_recovery, email_marketing, wholesale_b2b, and
discount_strategy via env vars:

  - SHOPAI_CART_RECOVERY_AGI_GUARDRAIL=1
  - SHOPAI_BROWSE_RECOVERY_AGI_GUARDRAIL=1
  - SHOPAI_EMAIL_MARKETING_AGI_GUARDRAIL=1
  - SHOPAI_WHOLESALE_B2B_AGI_GUARDRAIL=1
  - SHOPAI_DISCOUNT_STRATEGY_AGI_GUARDRAIL=1

For each engine, this file verifies:
  * Default behaviour unchanged (env var unset).
  * Block fires when env var ON and signal unambiguous.
  * Block records the refusal to record_writeback.
  * Mint short-circuits (the underlying ``_mint`` is never called).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


_UNAMBIGUOUS_NEGATIVE = {
    "similar_count": 5,
    "recent_negative": True,
    "recent_positive": False,
    "avg_relevance": 0.85,
}


# ─── cart_recovery ───────────────────────────────────────────


class TestCartRecoveryGuardrail:

    def test_off_proceeds(self, monkeypatch):
        from engines.cart_recovery.discount_minter import mint_recovery_code
        monkeypatch.delenv(
            "SHOPAI_CART_RECOVERY_AGI_GUARDRAIL", raising=False,
        )
        with patch(
            "engines.cart_recovery.discount_minter.capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.cart_recovery.discount_minter._mint",
            return_value={"code": "RECOVER-X", "discount_id": "gid"},
        ) as fake_mint:
            result = mint_recovery_code(
                incentive={"type": "percentage", "value": 10},
                customer={"id": "1"},
            )
        # Guardrail OFF → mint proceeds even with strong negative signal
        assert result is not None
        fake_mint.assert_called_once()

    def test_on_blocks(self, monkeypatch):
        from engines.cart_recovery.discount_minter import mint_recovery_code
        monkeypatch.setenv(
            "SHOPAI_CART_RECOVERY_AGI_GUARDRAIL", "1",
        )
        with patch(
            "engines.cart_recovery.discount_minter.capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.cart_recovery.discount_minter._mint",
        ) as fake_mint, patch(
            "engines.cart_recovery.discount_minter.record_writeback",
        ) as fake_record:
            result = mint_recovery_code(
                incentive={"type": "percentage", "value": 10},
                customer={"id": "1"},
            )
        assert result is None
        fake_mint.assert_not_called()
        fake_record.assert_called_once()
        assert fake_record.call_args.kwargs["success"] is False
        assert (
            "agi_guardrail_blocked"
            in fake_record.call_args.kwargs["error"]
        )


# ─── browse_recovery ─────────────────────────────────────────


class TestBrowseRecoveryGuardrail:

    def test_off_proceeds_per_offer(self, monkeypatch):
        from engines.browse_recovery.discount_minter import mint_offer_codes
        monkeypatch.delenv(
            "SHOPAI_BROWSE_RECOVERY_AGI_GUARDRAIL", raising=False,
        )
        offers = [{"user_id": "u1", "discount_pct": 20}]
        intent = [{"user_id": "u1", "purchase_likelihood": "high"}]
        with patch(
            "engines.browse_recovery.discount_minter.capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.browse_recovery.discount_minter._mint",
            return_value={"code": "BROWSE-X", "discount_id": "gid"},
        ) as fake_mint:
            mint_offer_codes(offers, intent)
        # Guardrail off → mint proceeds, offer is minted
        fake_mint.assert_called_once()
        assert offers[0]["minted"] is True

    def test_on_blocks_per_offer(self, monkeypatch):
        from engines.browse_recovery.discount_minter import mint_offer_codes
        monkeypatch.setenv(
            "SHOPAI_BROWSE_RECOVERY_AGI_GUARDRAIL", "1",
        )
        offers = [{"user_id": "u1", "discount_pct": 20}]
        intent = [{"user_id": "u1", "purchase_likelihood": "high"}]
        with patch(
            "engines.browse_recovery.discount_minter.capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.browse_recovery.discount_minter._mint",
        ) as fake_mint, patch(
            "engines.browse_recovery.discount_minter.record_writeback",
        ) as fake_record:
            mint_offer_codes(offers, intent)
        # Block → mint never called, offer stamped as skipped
        fake_mint.assert_not_called()
        assert offers[0]["minted"] is False
        fake_record.assert_called_once()
        assert fake_record.call_args.kwargs["success"] is False


# ─── email_marketing ─────────────────────────────────────────


class TestEmailMarketingGuardrail:

    def test_off_proceeds(self, monkeypatch):
        from engines.email_marketing.discount_minter import mint_campaign_code
        monkeypatch.delenv(
            "SHOPAI_EMAIL_MARKETING_AGI_GUARDRAIL", raising=False,
        )
        with patch(
            "engines.email_marketing.discount_minter.capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.email_marketing.discount_minter._mint",
            return_value={"code": "EMAIL-X", "discount_id": "gid"},
        ) as fake_mint:
            result = mint_campaign_code(
                goal="winter sale",
                discount={"type": "percentage", "value": 15},
            )
        assert result is not None
        fake_mint.assert_called_once()

    def test_on_blocks(self, monkeypatch):
        from engines.email_marketing.discount_minter import mint_campaign_code
        monkeypatch.setenv(
            "SHOPAI_EMAIL_MARKETING_AGI_GUARDRAIL", "1",
        )
        with patch(
            "engines.email_marketing.discount_minter.capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.email_marketing.discount_minter._mint",
        ) as fake_mint, patch(
            "engines.email_marketing.discount_minter.record_writeback",
        ) as fake_record:
            result = mint_campaign_code(
                goal="winter sale",
                discount={"type": "percentage", "value": 15},
            )
        assert result is None
        fake_mint.assert_not_called()
        fake_record.assert_called_once()


# ─── wholesale_b2b ───────────────────────────────────────────


class TestWholesaleB2bGuardrail:

    def test_off_proceeds(self, monkeypatch):
        from engines.wholesale_b2b.discount_minter import mint_wholesale_code
        monkeypatch.delenv(
            "SHOPAI_WHOLESALE_B2B_AGI_GUARDRAIL", raising=False,
        )
        with patch(
            "engines.wholesale_b2b.discount_minter.capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.wholesale_b2b.discount_minter._mint",
            return_value={"code": "WHOLESALE-X"},
        ) as fake_mint:
            result = mint_wholesale_code(
                order={"customer_id": "C1", "total": 1000},
                volume_discounts=[{"discount_pct": 20}],
            )
        assert result is not None
        fake_mint.assert_called_once()

    def test_on_blocks(self, monkeypatch):
        from engines.wholesale_b2b.discount_minter import mint_wholesale_code
        monkeypatch.setenv(
            "SHOPAI_WHOLESALE_B2B_AGI_GUARDRAIL", "1",
        )
        with patch(
            "engines.wholesale_b2b.discount_minter.capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.wholesale_b2b.discount_minter._mint",
        ) as fake_mint, patch(
            "engines.wholesale_b2b.discount_minter.record_writeback",
        ) as fake_record:
            result = mint_wholesale_code(
                order={"customer_id": "C1", "total": 1000},
                volume_discounts=[{"discount_pct": 20}],
            )
        assert result is None
        fake_mint.assert_not_called()
        fake_record.assert_called_once()


# ─── discount_strategy ───────────────────────────────────────


class TestDiscountStrategyGuardrail:

    def test_off_proceeds(self, monkeypatch):
        from engines.discount_strategy.discount_minter import (
            mint_strategy_code,
        )
        monkeypatch.delenv(
            "SHOPAI_DISCOUNT_STRATEGY_AGI_GUARDRAIL",
            raising=False,
        )
        with patch(
            "engines.discount_strategy.discount_minter."
            "capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.discount_strategy.discount_minter._mint",
            return_value={"code": "PROMO-X"},
        ) as fake_mint:
            result = mint_strategy_code(
                strategy={
                    "type": "percentage_off",
                    "depth_pct": 0.15,
                    "target_audience": "all",
                    "duration_hours": 24,
                },
                cannibalization_risk="low",
                confidence=0.9,
            )
        assert result is not None
        fake_mint.assert_called_once()

    def test_on_blocks(self, monkeypatch):
        from engines.discount_strategy.discount_minter import (
            mint_strategy_code,
        )
        monkeypatch.setenv(
            "SHOPAI_DISCOUNT_STRATEGY_AGI_GUARDRAIL", "1",
        )
        with patch(
            "engines.discount_strategy.discount_minter."
            "capture_decision_context",
            return_value={"metrics": _UNAMBIGUOUS_NEGATIVE},
        ), patch(
            "engines.discount_strategy.discount_minter._mint",
        ) as fake_mint, patch(
            "engines.discount_strategy.discount_minter.record_writeback",
        ) as fake_record:
            result = mint_strategy_code(
                strategy={
                    "type": "percentage_off",
                    "depth_pct": 0.15,
                    "target_audience": "all",
                    "duration_hours": 24,
                },
                cannibalization_risk="low",
                confidence=0.9,
            )
        assert result is None
        fake_mint.assert_not_called()
        fake_record.assert_called_once()
