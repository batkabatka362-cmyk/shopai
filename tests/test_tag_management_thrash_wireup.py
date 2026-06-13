"""Tests for tag_management applier thrash wireup (W921)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.context import active_store
from engines.tag_management.tag_applier import apply_tags


def _assign():
    return [{
        "product_id": "gid://shopify/Product/1",
        "tags": ["fresh-tag"],
    }]


def _products():
    return [{
        "id": "gid://shopify/Product/1",
        "tags": ["existing"],
    }]


def _patch_router():
    fake_router = MagicMock()
    fake_router.execute = MagicMock(
        return_value=MagicMock(ok=True, data={}),
    )
    return patch(
        "engines.tag_management.tag_applier._get_router",
        return_value=fake_router,
    ), fake_router


class TestThrashWireup:

    def test_calm_store_applies_normally(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_THRASH_GUARDRAIL", "1")
        fake_rep = type("R", (), {"verdict": "calm"})()
        router_patch, router = _patch_router()
        with patch(
            "core.automation.autonomy_overview_thrash."
            "compute_thrash",
            return_value=fake_rep,
        ), router_patch, patch(
            "engines.tag_management.tag_applier."
            "_get_capability_update_product",
            return_value="SHOPIFY_UPDATE_PRODUCT",
        ), active_store("store-7"):
            results = apply_tags(_assign(), _products())
        assert results[0]["applied"] is True
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
            "engines.tag_management.tag_applier."
            "_get_capability_update_product",
            return_value="SHOPIFY_UPDATE_PRODUCT",
        ), active_store("store-7"):
            results = apply_tags(_assign(), _products())
        assert results[0]["applied"] is False
        assert "thrash_guardrail_blocked" in results[0]["error"]
        router.execute.assert_not_called()

    def test_disabled_guardrail_no_check(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_THRASH_GUARDRAIL", False)
        router_patch, router = _patch_router()
        with router_patch, patch(
            "engines.tag_management.tag_applier."
            "_get_capability_update_product",
            return_value="SHOPIFY_UPDATE_PRODUCT",
        ), active_store("store-7"):
            results = apply_tags(_assign(), _products())
        assert results[0]["applied"] is True
