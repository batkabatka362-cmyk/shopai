"""Tests for affiliate commission_payer thrash wireup (W922)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.context import active_store
from engines.affiliate.commission_payer import pay_commissions


def _comms():
    return [{
        "partner_id": "p-1",
        "commission_amount": 25.0,
    }]


def _partners():
    return [{
        "id": "p-1",
        "email": "partner@example.com",
        "customer_id": "gid://shopify/Customer/1",
    }]


def _patch_router():
    fake_router = MagicMock()
    fake_router.execute = MagicMock(
        return_value=MagicMock(
            ok=True,
            data={
                "gift_card": {
                    "id": "gid://shopify/GiftCard/1",
                    "masked_code": "****ABCD",
                },
            },
        ),
    )
    return patch(
        "engines.affiliate.commission_payer._get_router",
        return_value=fake_router,
    ), fake_router


class TestThrashWireup:

    def test_calm_store_pays_normally(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_rep = type("R", (), {"verdict": "calm"})()
        router_patch, router = _patch_router()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ), router_patch, patch(
            "engines.affiliate.commission_payer."
            "_get_capability_create_gift_card",
            return_value="SHOPIFY_CREATE_GIFT_CARD",
        ), active_store("store-7"):
            results = pay_commissions(_comms(), _partners())
        assert results[0]["paid"] is True
        router.execute.assert_called_once()

    def test_thrashing_store_refuses_all(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_rep = type("R", (), {"verdict": "thrashing"})()
        router_patch, router = _patch_router()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ), router_patch, patch(
            "engines.affiliate.commission_payer."
            "_get_capability_create_gift_card",
            return_value="SHOPIFY_CREATE_GIFT_CARD",
        ), active_store("store-7"):
            results = pay_commissions(_comms(), _partners())
        assert results[0]["paid"] is False
        assert "thrash_guardrail_blocked" in results[0]["error"]
        router.execute.assert_not_called()

    def test_disabled_guardrail_no_check(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_THRASH_GUARDRAIL", False)
        router_patch, router = _patch_router()
        with router_patch, patch(
            "engines.affiliate.commission_payer."
            "_get_capability_create_gift_card",
            return_value="SHOPIFY_CREATE_GIFT_CARD",
        ), active_store("store-7"):
            results = pay_commissions(_comms(), _partners())
        assert results[0]["paid"] is True
