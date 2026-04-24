"""Wave 5 shopify_admin — shop + locales + currencies +
access scopes (+ 5b-f add to this file)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)
from core.adapters.shopify_admin.shop import (
    AccessScopes, Currencies, Locales, Shop,
)


def _fake_client():
    return MagicMock(spec=ShopifyAdminClient)


# ── Shop ──────────────────────────────────────────────────


class TestShopGet:
    def test_happy(self):
        c = _fake_client()
        c.get.return_value = {
            "shop": {
                "id": 99, "name": "Deguar",
                "email": "owner@deguar.com",
                "currency": "USD",
            },
        }
        shop = Shop.get(c)
        assert shop["name"] == "Deguar"

    def test_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Shop.get(c)


class TestShopMetafields:
    def test_list_with_namespace(self):
        c = _fake_client()
        c.get.return_value = {"metafields": [
            {"id": 1, "namespace": "shopai"}, "oops",
        ]}
        out = Shop.list_metafields(c, namespace="shopai")
        assert len(out) == 1
        params = c.get.call_args[1]["params"]
        assert params["namespace"] == "shopai"

    def test_list_limit_clamped(self):
        c = _fake_client()
        c.get.return_value = {"metafields": []}
        Shop.list_metafields(c, limit=9999)
        assert c.get.call_args[1]["params"]["limit"] == 250

    def test_create_requires_namespace_and_key(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Shop.create_metafield(
                c, namespace="", key="k", value="v",
            )
        with pytest.raises(ValueError):
            Shop.create_metafield(
                c, namespace="n", key="", value="v",
            )

    def test_create_happy(self):
        c = _fake_client()
        c.post.return_value = {"metafield": {"id": 1}}
        out = Shop.create_metafield(
            c, namespace="shopai", key="brand",
            value='{"voice":"calm_cozy"}',
            value_type="json",
        )
        assert out["id"] == 1
        body = c.post.call_args[0][1]["metafield"]
        assert body["namespace"] == "shopai"
        assert body["type"] == "json"

    def test_update_happy(self):
        c = _fake_client()
        c.put.return_value = {
            "metafield": {"id": 1, "value": "new"},
        }
        out = Shop.update_metafield(
            c, 1, value="new", value_type="json",
        )
        assert out["value"] == "new"
        body = c.put.call_args[0][1]["metafield"]
        assert body["id"] == 1
        assert body["value"] == "new"

    def test_delete(self):
        c = _fake_client()
        Shop.delete_metafield(c, 7)
        assert c.delete.call_args[0][0] == "metafields/7.json"


# ── AccessScopes ──────────────────────────────────────────


class TestAccessScopes:
    def test_list_scopes(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {
                "currentAppInstallation": {
                    "accessScopes": [
                        {"handle": "read_products"},
                        {"handle": "write_products"},
                        "malformed",
                    ],
                },
            },
        }
        out = AccessScopes.list_scopes(c)
        assert out == ["read_products", "write_products"]

    def test_has_scope_true(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currentAppInstallation": {
                "accessScopes": [{"handle": "write_products"}],
            }},
        }
        assert AccessScopes.has_scope(c, "write_products")

    def test_has_scope_false(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currentAppInstallation": {
                "accessScopes": [{"handle": "read_products"}],
            }},
        }
        assert not AccessScopes.has_scope(c, "write_orders")

    def test_has_scope_empty_handle(self):
        c = _fake_client()
        assert AccessScopes.has_scope(c, "") is False


# ── Locales ──────────────────────────────────────────────


class TestLocales:
    def test_list(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocales": [
                {"locale": "en", "primary": True},
                {"locale": "de", "primary": False},
                "oops",
            ]},
        }
        out = Locales.list_locales(c)
        assert len(out) == 2

    def test_enable_happy(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocaleEnable": {
                "shopLocale": {"locale": "de", "published": False},
                "userErrors": [],
            }},
        }
        out = Locales.enable(c, "de")
        assert out["locale"] == "de"

    def test_enable_requires_locale(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Locales.enable(c, "")

    def test_enable_user_error_raises(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocaleEnable": {
                "shopLocale": None,
                "userErrors": [{
                    "field": "locale",
                    "message": "not supported",
                }],
            }},
        }
        with pytest.raises(ShopifyAdminError):
            Locales.enable(c, "zz")

    def test_disable_returns_handle(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocaleDisable": {
                "locale": "de", "userErrors": [],
            }},
        }
        assert Locales.disable(c, "de") == "de"

    def test_set_published(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shopLocaleUpdate": {
                "shopLocale": {"locale": "de", "published": True},
                "userErrors": [],
            }},
        }
        out = Locales.set_published(
            c, "de", published=True,
        )
        assert out["published"] is True
        variables = c.graphql.call_args[1]["variables"]
        assert (
            variables["shopLocale"]["published"] is True
        )


# ── Currencies ───────────────────────────────────────────


class TestCurrencies:
    def test_get_settings(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"shop": {
                "currencyCode": "USD",
                "enabledPresentmentCurrencies": [
                    "USD", "EUR", "GBP",
                ],
                "currencyFormats": {
                    "moneyFormat": "${{amount}}",
                    "moneyWithCurrencyFormat": (
                        "${{amount}} USD"
                    ),
                },
            }},
        }
        out = Currencies.get_settings(c)
        assert out["base"] == "USD"
        assert "EUR" in out["enabled_presentment"]
        assert out["money_format"] == "${{amount}}"

    def test_enable_uppercases(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currencyActivate": {
                "currencySettings": [
                    {"currencyCode": "EUR", "enabled": True},
                ],
                "userErrors": [],
            }},
        }
        out = Currencies.enable(c, ["eur"])
        assert out[0]["currencyCode"] == "EUR"
        variables = c.graphql.call_args[1]["variables"]
        assert variables["currencies"] == ["EUR"]

    def test_enable_requires_list(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Currencies.enable(c, [])

    def test_disable_happy(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currencyDeactivate": {
                "currencySettings": [],
                "userErrors": [],
            }},
        }
        Currencies.disable(c, ["EUR"])
        variables = c.graphql.call_args[1]["variables"]
        assert variables["currencies"] == ["EUR"]

    def test_disable_user_error_raises(self):
        c = _fake_client()
        c.graphql.return_value = {
            "data": {"currencyDeactivate": {
                "currencySettings": [],
                "userErrors": [{
                    "field": "currencies",
                    "message": "cannot disable base",
                }],
            }},
        }
        with pytest.raises(ShopifyAdminError):
            Currencies.disable(c, ["USD"])
