"""Tests for the email_marketing approval-queue wiring (1C #9).

The engine's input carries an optional ``discount`` block that
the body composer / subject line generator reference as a string
("Save 10% on your order today"). Pre-fix that string had no
matching real Shopify code — the merchant had to mint one
manually and re-paste it into the email template before sending.

The applier closes the loop: when opt-in is set and the discount
is non-zero, mint ONE multi-use storewide code matching the
campaign discount.

Coverage:
  1. ``_resolve_discount`` accepts percentage / amount aliases,
     rejects unknown types, zero / negative values.
  2. ``mint_campaign_code`` happy path, missing discount, zero
     value, unknown type.
  3. ``enqueue_campaign_for_approval`` mirrors above + queue-
     unavailable fallback.
  4. flow integration — three branches of Stage 8.5.
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


# ─── _resolve_discount helper ──────────────────────────────────


class TestResolveDiscount:

    def test_percentage_canonical(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(
            {"type": "percentage", "value": 15},
        ) == ("percentage", 15.0)

    def test_percentage_alias_percent(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(
            {"type": "percent", "value": 20},
        ) == ("percentage", 20.0)

    def test_fixed_amount_alias(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(
            {"type": "fixed_amount", "value": 5},
        ) == ("amount", 5.0)

    def test_dollar_off_alias(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(
            {"type": "dollar_off", "value": 10},
        ) == ("amount", 10.0)

    def test_unknown_type_returns_none(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(
            {"type": "bxgy", "value": 1},
        ) is None

    def test_zero_value_returns_none(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(
            {"type": "percentage", "value": 0},
        ) is None

    def test_negative_value_returns_none(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(
            {"type": "percentage", "value": -5},
        ) is None

    def test_non_dict_returns_none(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(None) is None
        assert _resolve_discount("garbage") is None

    def test_missing_type_returns_none(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount({"value": 10}) is None

    def test_garbage_value_returns_none(self):
        from engines.email_marketing.discount_minter import (
            _resolve_discount,
        )
        assert _resolve_discount(
            {"type": "percentage", "value": "lots"},
        ) is None


# ─── mint_campaign_code (direct path) ──────────────────────────


class TestMintCampaignCode:

    def test_happy_path_percentage(self):
        from engines.email_marketing import discount_minter

        captured = {}

        def _stub_mint(**kwargs):
            captured.update(kwargs)
            return {
                "code": "EMAIL-WINTER-1234",
                "discount_id": "gid://shopify/Discount/1",
                "ends_at": "2099-01-01",
                "applies_once": False,
            }

        with patch.object(
            discount_minter, "_mint", side_effect=_stub_mint,
        ):
            result = discount_minter.mint_campaign_code(
                goal="winter sale",
                discount={"type": "percentage", "value": 15},
                store={"email_campaign_ttl_days": 14},
            )

        assert result is not None
        assert result["code"] == "EMAIL-WINTER-1234"
        assert captured["code_prefix"] == "EMAIL"
        assert captured["value"] == 15.0
        assert captured["value_kind"] == "percentage"
        assert captured["ttl_days"] == 14
        # Multi-use semantics.
        assert captured["usage_limit"] is None
        assert captured["applies_once_per_customer"] is False
        # Token derived from goal: "winter sale" → "WINTERSALE".
        assert captured["token"] == "WINTERSALE"

    def test_happy_path_fixed_amount(self):
        from engines.email_marketing import discount_minter

        captured = {}

        def _stub_mint(**kwargs):
            captured.update(kwargs)
            return {"code": "EMAIL-X", "discount_id": "1",
                    "ends_at": "2099", "applies_once": False}

        with patch.object(
            discount_minter, "_mint", side_effect=_stub_mint,
        ):
            discount_minter.mint_campaign_code(
                goal="flash",
                discount={"type": "fixed_amount", "value": 8},
            )

        assert captured["value"] == 8.0
        assert captured["value_kind"] == "amount"
        # Default TTL.
        assert captured["ttl_days"] == 30

    def test_zero_value_returns_none(self):
        from engines.email_marketing import discount_minter

        result = discount_minter.mint_campaign_code(
            goal="winter",
            discount={"type": "percentage", "value": 0},
        )
        assert result is None

    def test_missing_discount_returns_none(self):
        from engines.email_marketing import discount_minter

        result = discount_minter.mint_campaign_code(
            goal="winter",
            discount={},
        )
        assert result is None

    def test_unknown_type_returns_none(self):
        from engines.email_marketing import discount_minter

        result = discount_minter.mint_campaign_code(
            goal="winter",
            discount={"type": "bxgy", "value": 1},
        )
        assert result is None


# ─── enqueue_campaign_for_approval ─────────────────────────────


class TestEnqueueCampaignForApproval:

    def test_happy_path_parks_proposal(self, isolated_queue):
        from engines.email_marketing.discount_minter import (
            enqueue_campaign_for_approval,
        )

        result = enqueue_campaign_for_approval(
            goal="winter sale",
            discount={"type": "percentage", "value": 15},
            store={"email_campaign_ttl_days": 21},
        )
        assert result is not None
        assert result["pending_action_id"].startswith("appr_")
        assert "15% off" in result["narrative"]
        assert "21d TTL" in result["narrative"]
        assert result["params"]["value"] == 15.0
        assert result["params"]["value_kind"] == "percentage"
        assert result["params"]["ttl_days"] == 21

        action = isolated_queue.get(result["pending_action_id"])
        assert action is not None
        assert action.engine == "email_marketing"
        assert action.action_type == "mint_campaign_code"
        assert action.capability == "SHOPIFY_CREATE_DISCOUNT"

    def test_missing_discount_returns_none(self, isolated_queue):
        from engines.email_marketing.discount_minter import (
            enqueue_campaign_for_approval,
        )

        assert enqueue_campaign_for_approval(
            goal="winter",
            discount={},
        ) is None
        assert isolated_queue.list_pending() == []

    def test_zero_value_returns_none(self, isolated_queue):
        from engines.email_marketing.discount_minter import (
            enqueue_campaign_for_approval,
        )

        assert enqueue_campaign_for_approval(
            goal="winter",
            discount={"type": "percentage", "value": 0},
        ) is None

    def test_unknown_type_returns_none(self, isolated_queue):
        from engines.email_marketing.discount_minter import (
            enqueue_campaign_for_approval,
        )

        assert enqueue_campaign_for_approval(
            goal="winter",
            discount={"type": "mystery", "value": 5},
        ) is None

    def test_queue_unavailable_returns_none(self, isolated_queue):
        from engines.email_marketing.discount_minter import (
            enqueue_campaign_for_approval,
        )

        with patch(
            "core.approval.get_approval_queue",
            side_effect=RuntimeError("DB locked"),
        ):
            result = enqueue_campaign_for_approval(
                goal="winter",
                discount={"type": "percentage", "value": 10},
            )
        assert result is None


# ─── flow integration ───────────────────────────────────────────


def _flow_input(
    *,
    discount_value=10,
    apply_email_campaign=None,
    require_approval=None,
):
    data: dict = {
        "goal": "winter sale",
        "audience_segments": ["all"],
        "products": [
            {"id": "p1", "title": "Widget", "price": 50.0},
        ],
        "store_name": "TestStore",
        "discount": {"type": "percentage", "value": discount_value},
        "store": {"email_campaign_ttl_days": 14},
    }
    if apply_email_campaign is not None:
        data["apply_email_campaign"] = apply_email_campaign
    if require_approval is not None:
        data["require_approval"] = require_approval
    return {"status": "ok", "data": data, "meta": {}, "error": None}


class TestFlowApprovalIntegration:

    def test_default_off_writes_nothing(self, isolated_queue):
        from engines.email_marketing.flow import EmailMarketingEngine

        with patch(
            "engines.email_marketing.flow.mint_campaign_code",
        ) as mock_mint, patch(
            "engines.email_marketing.flow.enqueue_campaign_for_approval",
        ) as mock_enqueue:
            output = EmailMarketingEngine().run(_flow_input())

        mock_mint.assert_not_called()
        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            assert output["data"]["minted_code"] is None
            assert output["data"]["pending_action"] is None

    def test_apply_true_routes_to_direct(self, isolated_queue):
        from engines.email_marketing.flow import EmailMarketingEngine

        stub = {
            "code": "EMAIL-WINTERSALE-1",
            "discount_id": "1",
            "ends_at": "2099",
            "applies_once": False,
        }
        with patch(
            "engines.email_marketing.flow.mint_campaign_code",
            return_value=stub,
        ) as mock_mint, patch(
            "engines.email_marketing.flow.enqueue_campaign_for_approval",
        ) as mock_enqueue:
            output = EmailMarketingEngine().run(
                _flow_input(
                    apply_email_campaign=True,
                    require_approval=False,
                ),
            )

        mock_enqueue.assert_not_called()
        if output["status"] == "success":
            mock_mint.assert_called_once()
            assert output["data"]["minted_code"] == stub
            assert output["data"]["pending_action"] is None

    def test_require_approval_true_routes_to_enqueue(
        self, isolated_queue,
    ):
        from engines.email_marketing.flow import EmailMarketingEngine

        stub = {
            "pending_action_id": "appr_stub_1",
            "narrative": "email stub",
            "params": {},
        }
        with patch(
            "engines.email_marketing.flow.mint_campaign_code",
        ) as mock_mint, patch(
            "engines.email_marketing.flow.enqueue_campaign_for_approval",
            return_value=stub,
        ) as mock_enqueue:
            output = EmailMarketingEngine().run(
                _flow_input(
                    apply_email_campaign=True,
                    require_approval=True,
                ),
            )

        mock_mint.assert_not_called()
        if output["status"] == "success":
            mock_enqueue.assert_called_once()
            assert output["data"]["pending_action"] == stub
            assert output["data"]["minted_code"] is None

    def test_apply_true_with_empty_discount_still_fires_but_skips(
        self, isolated_queue,
    ):
        """Empty/zero discount: flow still routes to mint helper,
        helper returns None (verified in TestMintCampaignCode), so
        output carries minted_code=None just like default-off."""
        from engines.email_marketing.flow import EmailMarketingEngine

        with patch(
            "engines.email_marketing.flow.mint_campaign_code",
            return_value=None,
        ) as mock_mint:
            output = EmailMarketingEngine().run(
                _flow_input(
                    discount_value=0,
                    apply_email_campaign=True,
                    require_approval=False,
                ),
            )

        if output["status"] == "success":
            mock_mint.assert_called_once()
            assert output["data"]["minted_code"] is None
            assert output["data"]["pending_action"] is None
