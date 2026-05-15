"""Tests for the Phase 8 recorder coverage across the four
direct-mint minters that previously skipped feedback.

Before this PR (post #204), four engines minted Shopify discount
codes via ``engines._recovery_codes.mint_recovery_code`` but
DID NOT call ``record_writeback`` afterward. The minted codes
were real on Shopify, but the autonomous loop never saw the
mint event -- MemoryIntelligence / DataArchitecture / LearningLoop
were silent for these four engines:

  - browse_recovery
  - cart_recovery
  - email_marketing
  - wholesale_b2b

The fix wires ``record_writeback`` into each minter's success/fail
path. These tests are the regression guard: each minter MUST
emit a recorder call with the expected ``engine`` + ``action_type``
+ ``capability``.

Approach: patch ``record_writeback`` at the module-level import
in each minter (since the modules ``from ... import
record_writeback`` so patching the source module wouldn't
intercept the bound name). Stub the actual mint helper too so
no Shopify call happens.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ─── cart_recovery ────────────────────────────────────────────


class TestCartRecoveryRecorder:

    def test_recorder_called_on_successful_mint(self):
        from engines.cart_recovery import discount_minter as m
        fake_minted = {
            "code": "RECOVER-X",
            "discount_id": "gid://shopify/Discount/1",
            "ends_at": "2026-01-01T00:00:00Z",
            "applies_once": True,
        }
        with patch.object(
            m, "_mint", return_value=fake_minted,
        ), patch.object(
            m, "record_writeback",
        ) as recorder:
            result = m.mint_recovery_code(
                incentive={"type": "percentage", "value": 10},
                customer={"id": "gid://shopify/Customer/123"},
                store=None,
            )
        assert result is fake_minted
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["engine"] == "cart_recovery"
        assert kwargs["action_type"] == "mint_cart_recovery_code"
        assert kwargs["capability"] == "SHOPIFY_CREATE_DISCOUNT"
        assert kwargs["success"] is True

    def test_recorder_called_on_failed_mint(self):
        from engines.cart_recovery import discount_minter as m
        with patch.object(
            m, "_mint", return_value=None,
        ), patch.object(
            m, "record_writeback",
        ) as recorder:
            result = m.mint_recovery_code(
                incentive={"type": "percentage", "value": 10},
                customer={"id": "gid://shopify/Customer/123"},
                store=None,
            )
        assert result is None
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["success"] is False
        assert kwargs["error"] == "mint_returned_none"

    def test_unminitable_incentive_skips_mint_and_recorder(self):
        """Free-shipping / bundle / loyalty_points incentives don't
        mint a code -- they also shouldn't pollute the recorder
        because no action was taken."""
        from engines.cart_recovery import discount_minter as m
        with patch.object(
            m, "_mint",
        ) as mint, patch.object(
            m, "record_writeback",
        ) as recorder:
            m.mint_recovery_code(
                incentive={"type": "free_shipping", "value": 0},
                customer={"id": "1"},
                store=None,
            )
        mint.assert_not_called()
        recorder.assert_not_called()


# ─── browse_recovery ──────────────────────────────────────────


class TestBrowseRecoveryRecorder:

    def test_recorder_called_per_minted_offer(self):
        from engines.browse_recovery import discount_minter as m
        fake_minted = {
            "code": "BROWSE-X",
            "discount_id": "gid://shopify/Discount/2",
            "ends_at": "2026-01-01T00:00:00Z",
            "applies_once": True,
        }
        offers = [
            {
                "user_id": "u1",
                "discount_pct": 10.0,
                "purchase_likelihood": "high",
            },
        ]
        intent_scores = [
            {"user_id": "u1", "purchase_likelihood": "high"},
        ]
        with patch.object(
            m, "_mint", return_value=fake_minted,
        ), patch.object(
            m, "record_writeback",
        ) as recorder:
            m.mint_offer_codes(
                offers=offers,
                intent_scores=intent_scores,
                store=None,
            )
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["engine"] == "browse_recovery"
        assert kwargs["action_type"] == "mint_browse_recovery_code"
        assert kwargs["capability"] == "SHOPIFY_CREATE_DISCOUNT"
        assert kwargs["success"] is True


# ─── email_marketing ──────────────────────────────────────────


class TestEmailMarketingRecorder:

    def test_recorder_called_on_campaign_mint(self):
        from engines.email_marketing import discount_minter as m
        fake_minted = {
            "code": "EMAIL-X",
            "discount_id": "gid://shopify/Discount/3",
            "ends_at": "2026-01-01T00:00:00Z",
            "applies_once": False,
        }
        with patch.object(
            m, "_mint", return_value=fake_minted,
        ), patch.object(
            m, "record_writeback",
        ) as recorder:
            m.mint_campaign_code(
                goal="winter sale",
                discount={"type": "percentage", "value": 15},
                store=None,
            )
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["engine"] == "email_marketing"
        assert kwargs["action_type"] == "mint_campaign_code"
        assert kwargs["capability"] == "SHOPIFY_CREATE_DISCOUNT"


# ─── wholesale_b2b ────────────────────────────────────────────


class TestWholesaleB2BRecorder:

    def test_recorder_called_on_wholesale_mint(self):
        from engines.wholesale_b2b import discount_minter as m
        fake_minted = {
            "code": "WHOLESALE-X",
            "discount_id": "gid://shopify/Discount/4",
            "ends_at": "2026-01-01T00:00:00Z",
            "applies_once": True,
        }
        with patch.object(
            m, "_mint", return_value=fake_minted,
        ), patch.object(
            m, "record_writeback",
        ) as recorder:
            m.mint_wholesale_code(
                order={"customer_id": "gid://shopify/Customer/1"},
                volume_discounts=[
                    {"min_qty": 10, "discount_pct": 5},
                    {"min_qty": 50, "discount_pct": 15},
                ],
                store=None,
            )
        recorder.assert_called_once()
        kwargs = recorder.call_args.kwargs
        assert kwargs["engine"] == "wholesale_b2b"
        assert kwargs["action_type"] == "mint_wholesale_code"
        assert kwargs["capability"] == "SHOPIFY_CREATE_DISCOUNT"


# ─── Symmetric guarantee ──────────────────────────────────────


class TestSymmetricGuarantee:
    """Every discount minter in engines/ now has a record_writeback
    call adjacent to its _mint(...). This is the unified guarantee
    that any new discount-minter PR must preserve."""

    def test_every_discount_minter_has_a_recorder_call(self):
        from pathlib import Path
        engines_root = Path(__file__).resolve().parent.parent / "engines"
        offenders: list[str] = []
        for minter_path in engines_root.glob("*/discount_minter.py"):
            src = minter_path.read_text(encoding="utf-8")
            has_mint = "_mint(" in src or "mint_recovery_code(" in src
            has_recorder = "record_writeback(" in src
            if has_mint and not has_recorder:
                offenders.append(str(minter_path.relative_to(engines_root)))
        assert offenders == [], (
            "Discount minters that call _mint() must also call "
            f"record_writeback(): {offenders}"
        )
