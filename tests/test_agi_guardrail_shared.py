"""Tests for the shared v2 guardrail helpers in
``engines._agi_context``.

These were inlined in the loyalty minter as the reference v2
wiring (PR #245). This module extracts them so other engines
can opt-in via env-var with ~5 lines of code.

Loyalty's existing tests (``test_loyalty_agi_guardrail.py``)
still cover the end-to-end mint path; this file just exercises
the helpers in isolation.
"""
from __future__ import annotations

import pytest

from engines._agi_context import (
    GUARDRAIL_MIN_SIMILAR,
    explain_guardrail_block,
    guardrail_enabled,
    should_block_unambiguous_negative,
)


# ─── Per-engine env-var opt-in ───────────────────────────────


class TestGuardrailEnabled:

    def test_unset_default_off(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_LOYALTY_AGI_GUARDRAIL", raising=False,
        )
        assert guardrail_enabled("loyalty") is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_truthy_values_enable(self, monkeypatch, value):
        monkeypatch.setenv(
            "SHOPAI_CART_RECOVERY_AGI_GUARDRAIL", value,
        )
        assert guardrail_enabled("cart_recovery") is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
    def test_falsy_values_disable(self, monkeypatch, value):
        monkeypatch.setenv(
            "SHOPAI_BROWSE_RECOVERY_AGI_GUARDRAIL", value,
        )
        assert guardrail_enabled("browse_recovery") is False

    def test_per_engine_isolation(self, monkeypatch):
        """Each engine has its own switch -- enabling one
        engine's guardrail must NOT enable another's."""
        monkeypatch.setenv(
            "SHOPAI_LOYALTY_AGI_GUARDRAIL", "1",
        )
        monkeypatch.delenv(
            "SHOPAI_DISCOUNT_STRATEGY_AGI_GUARDRAIL",
            raising=False,
        )
        assert guardrail_enabled("loyalty") is True
        assert guardrail_enabled("discount_strategy") is False

    def test_case_insensitive_engine_name(self, monkeypatch):
        """Engine name is upper-cased before env lookup -- so
        callers can pass ``"loyalty"`` or ``"LOYALTY"``."""
        monkeypatch.setenv("SHOPAI_AFFILIATE_AGI_GUARDRAIL", "on")
        assert guardrail_enabled("affiliate") is True
        assert guardrail_enabled("AFFILIATE") is True
        assert guardrail_enabled("Affiliate") is True


# ─── Strict guardrail decision logic ─────────────────────────


class TestShouldBlockUnambiguousNegative:

    def test_empty_metrics_allows(self):
        assert should_block_unambiguous_negative(None) is False
        assert should_block_unambiguous_negative({}) is False

    def test_low_sample_allows(self):
        """Below GUARDRAIL_MIN_SIMILAR sparse signal isn't
        actionable."""
        assert should_block_unambiguous_negative({
            "similar_count": GUARDRAIL_MIN_SIMILAR - 1,
            "recent_negative": True,
            "recent_positive": False,
        }) is False

    def test_min_sample_with_negative_blocks(self):
        """Exactly at GUARDRAIL_MIN_SIMILAR + unambiguous
        negative => block."""
        assert should_block_unambiguous_negative({
            "similar_count": GUARDRAIL_MIN_SIMILAR,
            "recent_negative": True,
            "recent_positive": False,
        }) is True

    def test_no_negative_allows(self):
        assert should_block_unambiguous_negative({
            "similar_count": 10,
            "recent_negative": False,
            "recent_positive": True,
        }) is False

    def test_mixed_signal_allows(self):
        """Positive AND negative present => don't block.
        Mixed history gets the benefit of the doubt."""
        assert should_block_unambiguous_negative({
            "similar_count": 10,
            "recent_negative": True,
            "recent_positive": True,
        }) is False

    def test_invalid_similar_count_treated_as_zero(self):
        """Non-numeric similar_count → treated as 0 → no block."""
        assert should_block_unambiguous_negative({
            "similar_count": "garbage",
            "recent_negative": True,
            "recent_positive": False,
        }) is False


# ─── Audit explanation format ────────────────────────────────


class TestExplainGuardrailBlock:

    def test_includes_key_metrics(self):
        msg = explain_guardrail_block({
            "similar_count": 4,
            "avg_relevance": 0.85,
        })
        assert msg.startswith("agi_guardrail_blocked:")
        assert "similar=4" in msg
        assert "0.85" in msg
        assert "negative=true" in msg
        assert "positive=false" in msg

    def test_missing_avg_relevance_renders_zero(self):
        """The explanation should still produce a clean string
        even if avg_relevance is missing from the metrics dict."""
        msg = explain_guardrail_block({"similar_count": 3})
        assert "agi_guardrail_blocked" in msg
        assert "0.00" in msg
