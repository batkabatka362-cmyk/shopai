"""Tests for loyalty minter thrash guardrail wireup (W917)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.context import active_store
from engines.loyalty.discount_minter import mint_loyalty_code


def _reward():
    return {
        "type": "discount",
        "reward": "10% off next order",
        "points_cost": 100,
    }


class TestThrashWireup:

    def test_calm_store_mints_normally(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_rep = type("R", (), {"verdict": "calm"})()
        fake_mint = {"code": "LOYALTY-X", "discount_id": "1"}
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ), patch(
            "engines.loyalty.discount_minter._mint",
            return_value=fake_mint,
        ), active_store("store-7"):
            result = mint_loyalty_code("cust-1", _reward())
        assert result == fake_mint

    def test_thrashing_store_refuses_mint(
        self, monkeypatch,
    ):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_rep = type("R", (), {"verdict": "thrashing"})()
        spy_mint = MagicMock()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ), patch(
            "engines.loyalty.discount_minter._mint",
            spy_mint,
        ), active_store("store-7"):
            result = mint_loyalty_code("cust-1", _reward())
        assert result is None
        spy_mint.assert_not_called()

    def test_disabled_guardrail_no_check(
        self, monkeypatch,
    ):
        monkeypatch.delenv("SHOPAI_THRASH_GUARDRAIL", False)
        fake_mint = {"code": "LOYALTY-Y", "discount_id": "2"}
        with patch(
            "engines.loyalty.discount_minter._mint",
            return_value=fake_mint,
        ), active_store("store-7"):
            result = mint_loyalty_code("cust-1", _reward())
        assert result == fake_mint

    def test_no_active_store_no_block(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_mint = {"code": "LOYALTY-Z", "discount_id": "3"}
        with patch(
            "engines.loyalty.discount_minter._mint",
            return_value=fake_mint,
        ):
            result = mint_loyalty_code("cust-1", _reward())
        assert result == fake_mint
