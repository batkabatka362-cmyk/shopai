"""Tests for the loyalty engine's v2 AGI guardrail.

v1 (PR #236) made the loyalty minter CAPTURE the AGI signal and
fed it into ``record_writeback``. v2 (this PR) flips one engine
to actually ACT on the signal: when opted in via env var AND
the captured similar-decisions context is unambiguously
negative, refuse to mint.

This is intentionally strict — false positives (blocking a
mint we shouldn't) hurt revenue. The guardrail only fires when
ALL of:
  - similar_count >= 3 (sparse signal isn't actionable)
  - recent_negative is True (someone got hurt before)
  - recent_positive is False (mixed signal → don't block)

Other engines can copy this opt-in pattern when ready.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from engines.loyalty.discount_minter import (
    _agi_guardrail_enabled,
    _explain_block,
    _should_block_mint,
    mint_loyalty_code,
)


# ─── _should_block_mint helper ───────────────────────────────


class TestShouldBlock:

    def test_empty_signal_allows(self):
        # No signal → no block. Sparse data isn't actionable.
        assert _should_block_mint(None) is False
        assert _should_block_mint({}) is False

    def test_low_sample_allows(self):
        # Below the minimum similar_count → no block.
        assert _should_block_mint({
            "similar_count": 2,
            "recent_negative": True,
            "recent_positive": False,
        }) is False

    def test_no_negative_allows(self):
        # Plenty of similar decisions but none negative → no block.
        assert _should_block_mint({
            "similar_count": 10,
            "recent_negative": False,
            "recent_positive": True,
        }) is False

    def test_mixed_signal_allows(self):
        # Both positive AND negative outcomes → don't block.
        assert _should_block_mint({
            "similar_count": 5,
            "recent_negative": True,
            "recent_positive": True,
        }) is False

    def test_unambiguous_negative_blocks(self):
        # 3+ similar, has negative, NO positives → block.
        assert _should_block_mint({
            "similar_count": 3,
            "recent_negative": True,
            "recent_positive": False,
        }) is True


# ─── Env-var-gated opt-in ─────────────────────────────────────


class TestGuardrailEnabled:

    def test_unset_default_off(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", raising=False)
        assert _agi_guardrail_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_truthy_values_enable(self, monkeypatch, value):
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", value)
        assert _agi_guardrail_enabled() is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_falsy_values_disable(self, monkeypatch, value):
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", value)
        assert _agi_guardrail_enabled() is False


# ─── End-to-end: guardrail blocks when conditions met ────────


class TestGuardrailEndToEnd:

    def test_guardrail_off_no_signal_check(self, monkeypatch):
        """Default behaviour (guardrail OFF) -- signal is captured
        but never acts. The mint proceeds normally."""
        monkeypatch.delenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", raising=False)

        with patch(
            "engines.loyalty.discount_minter.capture_decision_context",
            return_value={"metrics": {
                "similar_count": 10,
                "recent_negative": True,
                "recent_positive": False,
            }},
        ), patch(
            "engines.loyalty.discount_minter._mint",
            return_value={"code": "LOYALTY-X", "discount_id": "gid"},
        ) as fake_mint:
            result = mint_loyalty_code(
                customer_id="gid://shopify/Customer/1",
                reward={"type": "discount", "reward": "10% off"},
            )
        # Guardrail off → mint proceeds even with strong negative signal
        assert result is not None
        assert result["code"] == "LOYALTY-X"
        fake_mint.assert_called_once()

    def test_guardrail_on_blocks_unambiguous_negative(
        self, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", "1")

        with patch(
            "engines.loyalty.discount_minter.capture_decision_context",
            return_value={"metrics": {
                "similar_count": 5,
                "recent_negative": True,
                "recent_positive": False,
                "avg_relevance": 0.85,
            }},
        ), patch(
            "engines.loyalty.discount_minter._mint",
        ) as fake_mint, patch(
            "engines.loyalty.discount_minter.record_writeback",
        ) as fake_record:
            result = mint_loyalty_code(
                customer_id="gid://shopify/Customer/1",
                reward={"type": "discount", "reward": "10% off"},
            )
        # Guardrail blocked the mint
        assert result is None
        # _mint was NEVER called -- short-circuited before the
        # Shopify call.
        fake_mint.assert_not_called()
        # The block was recorded with an explanatory reason.
        fake_record.assert_called_once()
        kwargs = fake_record.call_args.kwargs
        assert kwargs["success"] is False
        assert "agi_guardrail_blocked" in kwargs["error"]

    def test_guardrail_on_but_signal_mixed_proceeds(
        self, monkeypatch,
    ):
        """Mixed signal (positives + negatives) → don't block even
        when guardrail is on."""
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", "1")

        with patch(
            "engines.loyalty.discount_minter.capture_decision_context",
            return_value={"metrics": {
                "similar_count": 10,
                "recent_negative": True,
                "recent_positive": True,
            }},
        ), patch(
            "engines.loyalty.discount_minter._mint",
            return_value={"code": "LOYALTY-X"},
        ) as fake_mint:
            result = mint_loyalty_code(
                customer_id="gid://shopify/Customer/1",
                reward={"type": "discount", "reward": "10% off"},
            )
        assert result is not None
        fake_mint.assert_called_once()

    def test_guardrail_on_but_sparse_signal_proceeds(
        self, monkeypatch,
    ):
        """Sparse signal (below minimum count) → don't block."""
        monkeypatch.setenv("SHOPAI_LOYALTY_AGI_GUARDRAIL", "1")

        with patch(
            "engines.loyalty.discount_minter.capture_decision_context",
            return_value={"metrics": {
                "similar_count": 1,  # below minimum
                "recent_negative": True,
                "recent_positive": False,
            }},
        ), patch(
            "engines.loyalty.discount_minter._mint",
            return_value={"code": "LOYALTY-X"},
        ) as fake_mint:
            result = mint_loyalty_code(
                customer_id="gid://shopify/Customer/1",
                reward={"type": "discount", "reward": "10% off"},
            )
        assert result is not None
        fake_mint.assert_called_once()


# ─── _explain_block formatting ────────────────────────────────


class TestExplanationFormat:

    def test_explanation_includes_key_metrics(self):
        msg = _explain_block({
            "similar_count": 4,
            "avg_relevance": 0.75,
        })
        assert "similar=4" in msg
        assert "0.75" in msg
        assert "agi_guardrail_blocked" in msg
