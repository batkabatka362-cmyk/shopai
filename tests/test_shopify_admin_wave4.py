"""Tests for Wave 4 of shopify_admin: gift cards (+ wave 4b-e
land in subsequent commits on the same file)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)
from core.adapters.shopify_admin.gift_cards import GiftCards


def _fake_client():
    return MagicMock(spec=ShopifyAdminClient)


# ── GiftCards.list_cards ──────────────────────────────────


class TestGiftCardsList:
    def test_list_no_filter(self):
        c = _fake_client()
        c.get.return_value = {"gift_cards": [
            {"id": 1, "code": "AAAA-BBBB-CCCC-DDDD"},
            {"id": 2, "code": "EEEE-FFFF-GGGG-HHHH"},
        ]}
        out = GiftCards.list_cards(c)
        assert len(out) == 2
        assert c.get.call_args[0][0] == "gift_cards.json"
        assert c.get.call_args[1]["params"]["limit"] == 50

    def test_list_with_status_filter(self):
        c = _fake_client()
        c.get.return_value = {"gift_cards": []}
        GiftCards.list_cards(c, status="Enabled")
        params = c.get.call_args[1]["params"]
        assert params["status"] == "enabled"

    def test_list_limit_clamped(self):
        c = _fake_client()
        c.get.return_value = {"gift_cards": []}
        GiftCards.list_cards(c, limit=9999)
        assert c.get.call_args[1]["params"]["limit"] == 250

    def test_list_limit_floored(self):
        c = _fake_client()
        c.get.return_value = {"gift_cards": []}
        GiftCards.list_cards(c, limit=0)
        assert c.get.call_args[1]["params"]["limit"] == 1

    def test_list_skips_non_dict_rows(self):
        c = _fake_client()
        c.get.return_value = {"gift_cards": [
            {"id": 1}, "oops", None, {"id": 2},
        ]}
        out = GiftCards.list_cards(c)
        assert [r["id"] for r in out] == [1, 2]

    def test_list_empty_when_missing_key(self):
        c = _fake_client()
        c.get.return_value = {}
        assert GiftCards.list_cards(c) == []


# ── GiftCards.get_card ────────────────────────────────────


class TestGiftCardsGet:
    def test_get_happy(self):
        c = _fake_client()
        c.get.return_value = {
            "gift_card": {"id": 42, "balance": "20.00"},
        }
        card = GiftCards.get_card(c, 42)
        assert card["balance"] == "20.00"
        assert c.get.call_args[0][0] == "gift_cards/42.json"

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            GiftCards.get_card(c, 42)

    def test_get_non_dict_raises(self):
        c = _fake_client()
        c.get.return_value = {"gift_card": "oops"}
        with pytest.raises(ShopifyAdminError):
            GiftCards.get_card(c, 42)


# ── GiftCards.count ───────────────────────────────────────


class TestGiftCardsCount:
    def test_count_no_status(self):
        c = _fake_client()
        c.get.return_value = {"count": 17}
        assert GiftCards.count(c) == 17
        call = c.get.call_args
        # No params when status unset — keep URL clean.
        assert call[1]["params"] is None

    def test_count_with_status(self):
        c = _fake_client()
        c.get.return_value = {"count": 5}
        GiftCards.count(c, status="disabled")
        params = c.get.call_args[1]["params"]
        assert params["status"] == "disabled"

    def test_count_falls_back_to_zero(self):
        c = _fake_client()
        c.get.return_value = {"count": "not-a-number"}
        assert GiftCards.count(c) == 0

    def test_count_missing_key(self):
        c = _fake_client()
        c.get.return_value = {}
        assert GiftCards.count(c) == 0


# ── GiftCards.search ──────────────────────────────────────


class TestGiftCardsSearch:
    def test_search_happy(self):
        c = _fake_client()
        c.get.return_value = {"gift_cards": [
            {"id": 1, "last_characters": "ABCD"},
        ]}
        out = GiftCards.search(c, last_characters="ABCD")
        assert len(out) == 1
        params = c.get.call_args[1]["params"]
        assert params["query"] == "last_characters:ABCD"
        assert c.get.call_args[0][0] == "gift_cards/search.json"

    def test_search_strips_whitespace(self):
        c = _fake_client()
        c.get.return_value = {"gift_cards": []}
        GiftCards.search(c, last_characters="  XYZA  ")
        assert (
            c.get.call_args[1]["params"]["query"]
            == "last_characters:XYZA"
        )

    def test_search_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            GiftCards.search(c, last_characters="")

    def test_search_whitespace_only_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            GiftCards.search(c, last_characters="   ")


# ── GiftCards.create ──────────────────────────────────────


class TestGiftCardsCreate:
    def test_create_requires_positive_value(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            GiftCards.create(c, initial_value=0)
        with pytest.raises(ValueError):
            GiftCards.create(c, initial_value=-10)

    def test_create_requires_numeric_value(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            GiftCards.create(c, initial_value="not-a-number")

    def test_create_happy_minimal(self):
        c = _fake_client()
        c.post.return_value = {
            "gift_card": {"id": 99, "initial_value": "20.00"},
        }
        out = GiftCards.create(c, initial_value=20)
        assert out["id"] == 99
        path, body = c.post.call_args[0][0], c.post.call_args[0][1]
        assert path == "gift_cards.json"
        card = body["gift_card"]
        assert card["initial_value"] == "20.00"
        # Optional fields absent when not passed.
        assert "code" not in card
        assert "note" not in card
        assert "expires_on" not in card
        assert "currency" not in card
        assert "customer_id" not in card

    def test_create_full_payload(self):
        c = _fake_client()
        c.post.return_value = {"gift_card": {"id": 99}}
        GiftCards.create(
            c,
            initial_value=50,
            code="WELCOME-BACK-0001",
            note="Winback lapsed customer",
            expires_on="2026-12-31",
            currency="usd",
            customer_id=12345,
            template_suffix="winback",
        )
        card = c.post.call_args[0][1]["gift_card"]
        assert card["code"] == "WELCOME-BACK-0001"
        assert card["note"] == "Winback lapsed customer"
        assert card["expires_on"] == "2026-12-31"
        assert card["currency"] == "USD"
        assert card["customer_id"] == 12345
        assert card["template_suffix"] == "winback"

    def test_create_formats_value_two_decimals(self):
        c = _fake_client()
        c.post.return_value = {"gift_card": {"id": 1}}
        GiftCards.create(c, initial_value=7.5)
        assert (
            c.post.call_args[0][1]["gift_card"]["initial_value"]
            == "7.50"
        )

    def test_create_missing_response_raises(self):
        c = _fake_client()
        c.post.return_value = {}
        with pytest.raises(ShopifyAdminError):
            GiftCards.create(c, initial_value=10)


# ── GiftCards.update ──────────────────────────────────────


class TestGiftCardsUpdate:
    def test_update_empty_fields_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            GiftCards.update(c, 42, fields={})

    def test_update_immutable_field_raises(self):
        c = _fake_client()
        for immutable in ("initial_value", "balance", "code"):
            with pytest.raises(ValueError):
                GiftCards.update(c, 42, fields={immutable: "1"})

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {
            "gift_card": {"id": 42, "note": "VIP winback"},
        }
        out = GiftCards.update(
            c, 42, fields={"note": "VIP winback"},
        )
        assert out["note"] == "VIP winback"
        path, body = c.put.call_args[0][0], c.put.call_args[0][1]
        assert path == "gift_cards/42.json"
        assert body["gift_card"]["id"] == 42
        assert body["gift_card"]["note"] == "VIP winback"

    def test_update_missing_response_raises(self):
        c = _fake_client()
        c.put.return_value = {}
        with pytest.raises(ShopifyAdminError):
            GiftCards.update(
                c, 42, fields={"expires_on": "2027-01-01"},
            )


# ── GiftCards.disable ─────────────────────────────────────


class TestGiftCardsDisable:
    def test_disable_happy(self):
        c = _fake_client()
        c.post.return_value = {
            "gift_card": {"id": 42, "disabled_at": "now"},
        }
        out = GiftCards.disable(c, 42)
        assert out["disabled_at"] == "now"
        path, body = c.post.call_args[0][0], c.post.call_args[0][1]
        assert path == "gift_cards/42/disable.json"
        # Empty-body POST.
        assert body == {}

    def test_disable_missing_response_raises(self):
        c = _fake_client()
        c.post.return_value = {}
        with pytest.raises(ShopifyAdminError):
            GiftCards.disable(c, 42)
