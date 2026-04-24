"""Tests for Wave 4 of shopify_admin: gift cards + collections
(+ 4c-e land in subsequent commits on the same file)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)
from core.adapters.shopify_admin.collections import (
    Collects, CustomCollections, SmartCollections,
)
from core.adapters.shopify_admin.gift_cards import GiftCards
from core.adapters.shopify_admin.markets import (
    MarketCurrencies, Markets, MarketWebPresences,
)


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


# ── SmartCollections ──────────────────────────────────────


class TestSmartCollections:
    def test_list_no_filter(self):
        c = _fake_client()
        c.get.return_value = {"smart_collections": [
            {"id": 1, "title": "Winners"},
        ]}
        out = SmartCollections.list_collections(c)
        assert len(out) == 1
        assert c.get.call_args[0][0] == "smart_collections.json"

    def test_list_by_title(self):
        c = _fake_client()
        c.get.return_value = {"smart_collections": []}
        SmartCollections.list_collections(c, title="VIP")
        assert c.get.call_args[1]["params"]["title"] == "VIP"

    def test_list_limit_clamped(self):
        c = _fake_client()
        c.get.return_value = {"smart_collections": []}
        SmartCollections.list_collections(c, limit=9999)
        assert c.get.call_args[1]["params"]["limit"] == 250

    def test_list_skips_non_dict(self):
        c = _fake_client()
        c.get.return_value = {
            "smart_collections": [{"id": 1}, "oops"],
        }
        assert len(SmartCollections.list_collections(c)) == 1

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            SmartCollections.get(c, 1)

    def test_create_requires_title(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            SmartCollections.create(
                c, title="", rules=[{"column": "tag"}],
            )

    def test_create_requires_rules(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            SmartCollections.create(c, title="x", rules=[])

    def test_create_rejects_bad_sort_order(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            SmartCollections.create(
                c, title="x",
                rules=[{"column": "tag"}],
                sort_order="nonsense",
            )

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {
            "smart_collection": {"id": 99, "title": "Winners"},
        }
        out = SmartCollections.create(
            c,
            title="Winners",
            rules=[{
                "column": "tag",
                "relation": "equals",
                "condition": "winner",
            }],
            disjunctive=True,
            body_html="<p>Best sellers</p>",
            published=False,
            sort_order="price-desc",
        )
        assert out["id"] == 99
        body = c.post.call_args[0][1]["smart_collection"]
        assert body["title"] == "Winners"
        assert body["disjunctive"] is True
        assert body["published"] is False
        assert body["sort_order"] == "price-desc"
        assert body["rules"][0]["condition"] == "winner"
        assert body["body_html"] == "<p>Best sellers</p>"

    def test_create_missing_response_raises(self):
        c = _fake_client()
        c.post.return_value = {}
        with pytest.raises(ShopifyAdminError):
            SmartCollections.create(
                c, title="x", rules=[{"column": "tag"}],
            )

    def test_update_empty_fields_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            SmartCollections.update(c, 1, fields={})

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {
            "smart_collection": {"id": 1, "title": "New"},
        }
        out = SmartCollections.update(
            c, 1, fields={"title": "New"},
        )
        assert out["title"] == "New"
        body = c.put.call_args[0][1]["smart_collection"]
        assert body["id"] == 1

    def test_delete(self):
        c = _fake_client()
        SmartCollections.delete(c, 42)
        assert c.delete.call_args[0][0] == (
            "smart_collections/42.json"
        )


# ── CustomCollections ─────────────────────────────────────


class TestCustomCollections:
    def test_list_with_filters(self):
        c = _fake_client()
        c.get.return_value = {"custom_collections": []}
        CustomCollections.list_collections(
            c, title="Sale", published_status="published",
        )
        params = c.get.call_args[1]["params"]
        assert params["title"] == "Sale"
        assert params["published_status"] == "published"

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            CustomCollections.get(c, 1)

    def test_create_requires_title(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            CustomCollections.create(c, title="")

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {
            "custom_collection": {"id": 7, "title": "Sale"},
        }
        out = CustomCollections.create(
            c,
            title="Sale",
            body_html="<p>x</p>",
            published=False,
            sort_order="manual",
            template_suffix="sale",
        )
        assert out["id"] == 7
        body = c.post.call_args[0][1]["custom_collection"]
        assert body["title"] == "Sale"
        assert body["published"] is False
        assert body["template_suffix"] == "sale"

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {
            "custom_collection": {"id": 7},
        }
        CustomCollections.update(
            c, 7, fields={"published": True},
        )
        body = c.put.call_args[0][1]["custom_collection"]
        assert body["id"] == 7
        assert body["published"] is True

    def test_delete(self):
        c = _fake_client()
        CustomCollections.delete(c, 7)
        assert c.delete.call_args[0][0] == (
            "custom_collections/7.json"
        )


# ── Collects ──────────────────────────────────────────────


class TestCollects:
    def test_list_by_collection(self):
        c = _fake_client()
        c.get.return_value = {"collects": [
            {"id": 1, "product_id": 11, "collection_id": 22},
        ]}
        out = Collects.list_collects(c, collection_id=22)
        assert len(out) == 1
        assert (
            c.get.call_args[1]["params"]["collection_id"] == 22
        )

    def test_list_by_product(self):
        c = _fake_client()
        c.get.return_value = {"collects": []}
        Collects.list_collects(c, product_id=55)
        assert c.get.call_args[1]["params"]["product_id"] == 55

    def test_list_both_filters(self):
        c = _fake_client()
        c.get.return_value = {"collects": []}
        Collects.list_collects(
            c, product_id=1, collection_id=2,
        )
        params = c.get.call_args[1]["params"]
        assert params["product_id"] == 1
        assert params["collection_id"] == 2

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {
            "collect": {"id": 9, "product_id": 1, "collection_id": 2},
        }
        out = Collects.create(
            c, product_id=1, collection_id=2, position=3,
        )
        assert out["id"] == 9
        body = c.post.call_args[0][1]["collect"]
        assert body["product_id"] == 1
        assert body["collection_id"] == 2
        assert body["position"] == 3

    def test_create_without_position(self):
        c = _fake_client()
        c.post.return_value = {"collect": {"id": 9}}
        Collects.create(c, product_id=1, collection_id=2)
        body = c.post.call_args[0][1]["collect"]
        assert "position" not in body

    def test_create_missing_response_raises(self):
        c = _fake_client()
        c.post.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Collects.create(c, product_id=1, collection_id=2)

    def test_delete(self):
        c = _fake_client()
        Collects.delete(c, 42)
        assert c.delete.call_args[0][0] == "collects/42.json"

    def test_remove_product_found(self):
        c = _fake_client()
        c.get.return_value = {"collects": [
            {"id": 77, "product_id": 1, "collection_id": 2},
            {"id": 78, "product_id": 1, "collection_id": 3},
        ]}
        ok = Collects.remove_product(
            c, product_id=1, collection_id=3,
        )
        assert ok is True
        # Should have deleted the second row.
        assert c.delete.call_args[0][0] == "collects/78.json"

    def test_remove_product_not_found_idempotent(self):
        c = _fake_client()
        c.get.return_value = {"collects": [
            {"id": 77, "product_id": 1, "collection_id": 2},
        ]}
        ok = Collects.remove_product(
            c, product_id=1, collection_id=999,
        )
        assert ok is False
        c.delete.assert_not_called()


# ── Markets ───────────────────────────────────────────────


class TestMarkets:
    def test_list_markets(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {"markets": {"edges": [
            {"node": {"id": "gid://shopify/Market/1", "name": "US"}},
            {"node": {"id": "gid://shopify/Market/2", "name": "EU"}},
            "not-a-dict",
        ]}}}
        out = Markets.list_markets(c)
        assert len(out) == 2
        call = c.graphql.call_args
        assert call[1]["variables"]["first"] == 50

    def test_list_limit_clamped(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"markets": {"edges": []}},
        }
        Markets.list_markets(c, limit=9999)
        assert c.graphql.call_args[1]["variables"]["first"] == 250

    def test_get_happy(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {"market": {
            "id": "gid://shopify/Market/1", "name": "US",
        }}}
        out = Markets.get(c, 1)
        assert out["name"] == "US"
        # Bare int promoted to GID.
        assert (
            c.graphql.call_args[1]["variables"]["id"]
            == "gid://shopify/Market/1"
        )

    def test_get_accepts_full_gid(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {"market": {
            "id": "gid://shopify/Market/7",
        }}}
        Markets.get(c, "gid://shopify/Market/7")
        assert (
            c.graphql.call_args[1]["variables"]["id"]
            == "gid://shopify/Market/7"
        )

    def test_get_missing_raises(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {}}
        with pytest.raises(ShopifyAdminError):
            Markets.get(c, 1)

    def test_create_requires_name(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Markets.create(c, name="", country_codes=["US"])

    def test_create_requires_countries(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Markets.create(c, name="EU", country_codes=[])

    def test_create_happy(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {"marketCreate": {
            "market": {
                "id": "gid://shopify/Market/99",
                "name": "EU",
                "enabled": True,
            },
            "userErrors": [],
        }}}
        out = Markets.create(
            c, name="EU", country_codes=["de", "FR", "it"],
        )
        assert out["id"] == "gid://shopify/Market/99"
        variables = c.graphql.call_args[1]["variables"]
        codes = [
            r["countryCode"]
            for r in variables["input"]["regions"]
        ]
        # Uppercased.
        assert codes == ["DE", "FR", "IT"]
        assert variables["input"]["name"] == "EU"
        assert variables["input"]["enabled"] is True

    def test_create_user_error_raises(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {"marketCreate": {
            "market": None,
            "userErrors": [{
                "field": "regions",
                "message": "already part of another market",
            }],
        }}}
        with pytest.raises(ShopifyAdminError) as exc:
            Markets.create(
                c, name="EU", country_codes=["DE"],
            )
        assert "already part of another market" in str(exc.value)

    def test_update_requires_any_field(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Markets.update(c, 1)

    def test_update_happy(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {"marketUpdate": {
            "market": {
                "id": "gid://shopify/Market/1",
                "name": "USA",
                "enabled": False,
            },
            "userErrors": [],
        }}}
        out = Markets.update(
            c, 1, name="USA", enabled=False,
        )
        assert out["enabled"] is False
        variables = c.graphql.call_args[1]["variables"]
        assert variables["input"]["name"] == "USA"
        assert variables["input"]["enabled"] is False

    def test_delete_returns_gid(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {"marketDelete": {
            "deletedId": "gid://shopify/Market/1",
            "userErrors": [],
        }}}
        out = Markets.delete(c, 1)
        assert out == "gid://shopify/Market/1"

    def test_delete_primary_blocked_by_user_error(self):
        c = _fake_client()
        c.graphql.return_value = {"data": {"marketDelete": {
            "deletedId": None,
            "userErrors": [{
                "field": "id",
                "message": "primary market cannot be deleted",
            }],
        }}}
        with pytest.raises(ShopifyAdminError):
            Markets.delete(c, 1)


# ── MarketWebPresences ────────────────────────────────────


class TestMarketWebPresences:
    def test_requires_default_locale(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            MarketWebPresences.create(
                c,
                market_id=1,
                default_locale="",
                subfolder_suffix="de",
            )

    def test_exactly_one_of_subfolder_or_domain(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            MarketWebPresences.create(
                c, market_id=1, default_locale="de",
            )
        with pytest.raises(ValueError):
            MarketWebPresences.create(
                c,
                market_id=1,
                default_locale="de",
                subfolder_suffix="de",
                domain_id=99,
            )

    def test_create_with_subfolder(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"marketWebPresenceCreate": {
                "market": {
                    "id": "gid://shopify/Market/1",
                    "webPresence": {
                        "id": "gid://shopify/MarketWebPresence/2",
                        "subfolderSuffix": "de",
                        "defaultLocale": "de",
                    },
                },
                "userErrors": [],
            }},
        }
        out = MarketWebPresences.create(
            c,
            market_id=1,
            default_locale="de",
            subfolder_suffix="de",
        )
        assert out["webPresence"]["subfolderSuffix"] == "de"
        input_ = c.graphql.call_args[1]["variables"]["input"]
        assert input_["subfolderSuffix"] == "de"
        assert "domainId" not in input_

    def test_create_with_domain_id_promoted(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"marketWebPresenceCreate": {
                "market": {"id": "gid://shopify/Market/1"},
                "userErrors": [],
            }},
        }
        MarketWebPresences.create(
            c,
            market_id=1,
            default_locale="de",
            domain_id=12345,
        )
        input_ = c.graphql.call_args[1]["variables"]["input"]
        assert input_["domainId"] == (
            "gid://shopify/Domain/12345"
        )


# ── MarketCurrencies ──────────────────────────────────────


class TestMarketCurrencies:
    def test_requires_some_field(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            MarketCurrencies.update(c, market_id=1)

    def test_update_base_currency(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"marketCurrencySettingsUpdate": {
                "market": {
                    "id": "gid://shopify/Market/1",
                    "currencySettings": {
                        "baseCurrency": {"currencyCode": "EUR"},
                        "localCurrencies": True,
                    },
                },
                "userErrors": [],
            }},
        }
        out = MarketCurrencies.update(
            c,
            market_id=1,
            base_currency="eur",
            local_currencies=True,
        )
        cs = out["currencySettings"]
        assert cs["baseCurrency"]["currencyCode"] == "EUR"
        input_ = c.graphql.call_args[1]["variables"]["input"]
        assert input_["baseCurrency"] == "EUR"
        assert input_["localCurrencies"] is True

    def test_update_user_error_raises(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"marketCurrencySettingsUpdate": {
                "market": None,
                "userErrors": [{
                    "field": "baseCurrency",
                    "message": "unsupported currency",
                }],
            }},
        }
        with pytest.raises(ShopifyAdminError):
            MarketCurrencies.update(
                c, market_id=1, base_currency="XYZ",
            )
