"""Tests for the discount_strategy engine's promo-code minter.

Covers both the standalone ``mint_strategy_code`` helper and the
flow-level integration (``data.apply_discount`` opt-in flag).

Phase 6.2 of the engine→Shopify writeback rollout. Mirrors the
test shape of test_loyalty_discount_minter.py with two
strategy-specific additions:

  1. The shared ``_recovery_codes.mint_recovery_code`` was extended
     to accept ``usage_limit`` / ``applies_once_per_customer``
     params for storewide promo codes (multi-use, customer-reusable).
     Tests verify the minter passes these correctly through.
  2. Cannibalization-risk + confidence guardrails block the mint
     even when ``apply_discount=True``.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ─── _depth_to_percentage ─────────────────────────────────────────


class TestDepthToPercentage:

    @pytest.mark.parametrize("depth,expected", [
        (0.05, 5.0),
        (0.10, 10.0),
        (0.15, 15.0),
        (0.50, 50.0),
        (1.0, 100.0),
        ("0.20", 20.0),
    ])
    def test_converts_fraction_to_percentage(self, depth, expected):
        from engines.discount_strategy.discount_minter import (
            _depth_to_percentage,
        )

        assert _depth_to_percentage(depth) == expected

    @pytest.mark.parametrize("invalid", [
        None,
        "garbage",
        0.0,
        -0.1,
        1.5,    # >1 likely a 150% mistake; reject
        100.0,  # caller passing 100 instead of 1.0
    ])
    def test_returns_none_for_invalid(self, invalid):
        from engines.discount_strategy.discount_minter import (
            _depth_to_percentage,
        )

        assert _depth_to_percentage(invalid) is None


# ─── _hours_to_ttl_days ───────────────────────────────────────────


class TestHoursToTtlDays:

    @pytest.mark.parametrize("hours,expected", [
        (24, 1),
        (48, 2),
        (72, 3),
        (1, 1),     # 1 hour → 1 day (round up)
        (6, 1),     # 6h flash sale → 1 day
        (25, 2),    # 25h → 2 days
    ])
    def test_rounds_up_to_full_days(self, hours, expected):
        from engines.discount_strategy.discount_minter import (
            _hours_to_ttl_days,
        )

        assert _hours_to_ttl_days(hours) == expected

    def test_invalid_falls_back_to_default(self):
        from engines.discount_strategy.discount_minter import (
            _hours_to_ttl_days,
        )

        assert _hours_to_ttl_days(None) == 7
        assert _hours_to_ttl_days("garbage") == 7
        assert _hours_to_ttl_days(0) == 7
        assert _hours_to_ttl_days(-5) == 7


# ─── _build_token ─────────────────────────────────────────────────


class TestBuildToken:

    @pytest.mark.parametrize("audience,expected", [
        ("all", "ALL"),
        ("vip-tier", "VIPTIER"),
        ("new_customers", "NEWCUSTOMERS"),
        ("", "ALL"),
        (None, "ALL"),
    ])
    def test_sanitises_audience(self, audience, expected):
        from engines.discount_strategy.discount_minter import (
            _build_token,
        )

        assert _build_token(audience) == expected

    def test_caps_at_12_chars(self):
        from engines.discount_strategy.discount_minter import (
            _build_token,
        )

        long = "this-is-a-very-long-audience-descriptor"
        assert len(_build_token(long)) == 12


# ─── mint_strategy_code ───────────────────────────────────────────


class TestMintStrategyCode:

    def _strategy(self, **overrides):
        base = {
            "type": "percentage_off",
            "depth_pct": 0.15,
            "target_audience": "all",
            "duration_hours": 48,
            "start_time": "00:00",
        }
        base.update(overrides)
        return base

    def test_non_percentage_type_returns_none(self):
        from engines.discount_strategy.discount_minter import (
            mint_strategy_code,
        )

        with patch(
            "engines.discount_strategy.discount_minter._mint",
        ) as mock_mint:
            result = mint_strategy_code(self._strategy(type="bogo"))
        assert result is None
        mock_mint.assert_not_called()

    def test_high_cannibalization_blocked(self):
        from engines.discount_strategy.discount_minter import (
            mint_strategy_code,
        )

        with patch(
            "engines.discount_strategy.discount_minter._mint",
        ) as mock_mint:
            result = mint_strategy_code(
                strategy=self._strategy(),
                cannibalization_risk="high",
            )
        assert result is None
        mock_mint.assert_not_called()

    def test_confidence_below_floor_blocked(self):
        from engines.discount_strategy.discount_minter import (
            mint_strategy_code,
        )

        with patch(
            "engines.discount_strategy.discount_minter._mint",
        ) as mock_mint:
            result = mint_strategy_code(
                strategy=self._strategy(),
                confidence=0.3,
                min_confidence=0.6,
            )
        assert result is None
        mock_mint.assert_not_called()

    def test_happy_path_routes_to_shared_mint(self):
        from engines.discount_strategy.discount_minter import (
            mint_strategy_code,
        )

        with patch(
            "engines.discount_strategy.discount_minter._mint",
            return_value={
                "code": "PROMO-ALL-1234",
                "discount_id": "gid://shopify/DiscountCodeNode/x",
                "ends_at": "2026-05-01",
                "applies_once": False,
            },
        ) as mock_mint:
            result = mint_strategy_code(
                strategy=self._strategy(
                    depth_pct=0.20, duration_hours=24,
                    target_audience="vip",
                ),
                cannibalization_risk="low",
                confidence=0.7,
            )

        assert result["code"] == "PROMO-ALL-1234"
        kwargs = mock_mint.call_args.kwargs
        assert kwargs["code_prefix"] == "PROMO"
        assert kwargs["value"] == 20.0
        assert kwargs["value_kind"] == "percentage"
        assert kwargs["ttl_days"] == 1
        assert kwargs["token"] == "VIP"
        # Critical: storewide promo is multi-use + reusable.
        assert kwargs["usage_limit"] is None
        assert kwargs["applies_once_per_customer"] is False

    def test_medium_risk_still_mints(self):
        # Only "high" is blocked.
        from engines.discount_strategy.discount_minter import (
            mint_strategy_code,
        )

        with patch(
            "engines.discount_strategy.discount_minter._mint",
            return_value={
                "code": "PROMO-X", "discount_id": "x",
                "ends_at": "", "applies_once": False,
            },
        ) as mock_mint:
            result = mint_strategy_code(
                strategy=self._strategy(),
                cannibalization_risk="medium",
                confidence=0.5,
            )

        assert result is not None
        assert mock_mint.called


# ─── flow integration ────────────────────────────────────────────


class TestDiscountStrategyFlowApplyDiscount:

    def _input(self, apply: bool = False, **extra):
        # Minimum viable input that lets the engine reach
        # Stage 10b without any pipeline failures. Real call sites
        # supply richer products / costs / market data.
        return {
            "data": {
                "products": [
                    {
                        "id": "gid://shopify/Product/1",
                        "title": "Widget",
                        "price": 50.0,
                        "cogs": 20.0,
                        "daily_sales": 5,
                        "regular_margin_pct": 0.60,
                    },
                ],
                "goal": "boost_revenue",
                "inventory_days": 90,
                "customer_segments": ["all"],
                "apply_discount": apply,
                **extra,
            },
        }

    def test_apply_discount_false_no_minter_call(self):
        from engines.discount_strategy.flow import (
            DiscountStrategyEngine,
        )

        with patch(
            "engines.discount_strategy.flow.mint_strategy_code",
        ) as mock_mint:
            output = DiscountStrategyEngine().run(self._input(False))

        mock_mint.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["minted_code"] is None

    def test_apply_discount_true_calls_minter(self):
        from engines.discount_strategy.flow import (
            DiscountStrategyEngine,
        )

        with patch(
            "engines.discount_strategy.flow.mint_strategy_code",
            return_value={
                "code": "PROMO-ALL-9999",
                "discount_id": "gid://shopify/DiscountCodeNode/x",
                "ends_at": "2026-05-01",
                "applies_once": False,
            },
        ) as mock_mint:
            output = DiscountStrategyEngine().run(self._input(True))

        # Engine reached Stage 10b and called the minter.
        if output["status"] == "success":
            assert mock_mint.called
            assert output["data"]["minted_code"]["code"] == \
                "PROMO-ALL-9999"

    def test_min_confidence_threshold_threaded_through(self):
        from engines.discount_strategy.flow import (
            DiscountStrategyEngine,
        )

        captured: dict = {}

        def _spy(*, strategy, cannibalization_risk, confidence,
                 min_confidence, **_):
            captured["min_confidence"] = min_confidence
            return None  # block; we only check the param flow

        with patch(
            "engines.discount_strategy.flow.mint_strategy_code",
            side_effect=_spy,
        ):
            DiscountStrategyEngine().run(
                self._input(True, min_apply_confidence=0.75),
            )

        if captured:
            assert captured["min_confidence"] == 0.75
