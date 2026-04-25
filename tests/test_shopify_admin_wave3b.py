"""Tests for Wave 3b of shopify_admin: themes + shipping."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.adapters.shopify_admin.client import (
    ShopifyAdminClient, ShopifyAdminError,
)
from core.adapters.shopify_admin.themes import (
    Themes, ThemeAssets,
)
from core.adapters.shopify_admin.shipping import (
    CarrierServices, ShippingRates, ShippingZones,
)


def _fake_client():
    return MagicMock(spec=ShopifyAdminClient)


# ── Themes ────────────────────────────────────────────────


class TestThemes:
    def test_list_no_filter(self):
        c = _fake_client()
        c.get.return_value = {"themes": [
            {"id": 1, "role": "main"},
            {"id": 2, "role": "unpublished"},
        ]}
        out = Themes.list_themes(c)
        assert len(out) == 2

    def test_list_by_role(self):
        c = _fake_client()
        c.get.return_value = {"themes": [
            {"id": 1, "role": "main"},
        ]}
        Themes.list_themes(c, role="main")
        params = c.get.call_args[1]["params"]
        assert params["role"] == "main"

    def test_list_invalid_role_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Themes.list_themes(c, role="bad")

    def test_get(self):
        c = _fake_client()
        c.get.return_value = {"theme": {"id": 42}}
        assert Themes.get(c, 42)["id"] == 42

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            Themes.get(c, 42)

    def test_get_main_returns_live(self):
        c = _fake_client()
        c.get.return_value = {"themes": [
            {"id": 1, "role": "main", "name": "Dawn"},
        ]}
        theme = Themes.get_main(c)
        assert theme["name"] == "Dawn"

    def test_get_main_none_when_no_main(self):
        c = _fake_client()
        c.get.return_value = {"themes": []}
        assert Themes.get_main(c) is None

    def test_create_requires_name(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Themes.create(c, name="")

    def test_create_invalid_role_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Themes.create(c, name="X", role="bogus")

    def test_create_defaults_unpublished(self):
        c = _fake_client()
        c.post.return_value = {"theme": {"id": 1}}
        Themes.create(c, name="Dawn v2", src="https://x.zip")
        body = c.post.call_args[0][1]
        assert body["theme"]["role"] == "unpublished"
        assert body["theme"]["src"] == "https://x.zip"

    def test_update_injects_id(self):
        c = _fake_client()
        c.put.return_value = {"theme": {"id": 42}}
        Themes.update(c, 42, fields={"name": "New"})
        body = c.put.call_args[0][1]
        assert body["theme"]["id"] == 42
        assert body["theme"]["name"] == "New"

    def test_update_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            Themes.update(c, 42, fields={})

    def test_publish_sets_main(self):
        c = _fake_client()
        c.put.return_value = {"theme": {"id": 42}}
        Themes.publish(c, 42)
        body = c.put.call_args[0][1]
        assert body["theme"]["role"] == "main"

    def test_delete(self):
        c = _fake_client()
        Themes.delete(c, 42)
        c.delete.assert_called_once()


class TestThemeAssets:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {"assets": [
            {"key": "layout/theme.liquid"},
        ]}
        out = ThemeAssets.list_assets(c, 42)
        assert len(out) == 1
        assert out[0]["key"] == "layout/theme.liquid"

    def test_get_asset_by_key(self):
        c = _fake_client()
        c.get.return_value = {"asset": {
            "key": "snippets/shopai-schema.liquid",
            "value": "{% comment %}shopai{% endcomment %}",
        }}
        asset = ThemeAssets.get_asset(
            c, 42, key="snippets/shopai-schema.liquid",
        )
        assert "shopai" in asset["value"]
        params = c.get.call_args[1]["params"]
        assert params["asset[key]"] == (
            "snippets/shopai-schema.liquid"
        )

    def test_get_asset_empty_key_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ThemeAssets.get_asset(c, 42, key="")

    def test_get_asset_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            ThemeAssets.get_asset(
                c, 42, key="snippets/shopai.liquid",
            )

    def test_upsert_with_value(self):
        c = _fake_client()
        c.put.return_value = {"asset": {
            "key": "snippets/x.liquid",
        }}
        ThemeAssets.upsert_asset(
            c, 42,
            key="snippets/x.liquid",
            value="<!-- x -->",
        )
        body = c.put.call_args[0][1]
        assert body["asset"]["value"] == "<!-- x -->"

    def test_upsert_with_src(self):
        c = _fake_client()
        c.put.return_value = {"asset": {
            "key": "assets/logo.png",
        }}
        ThemeAssets.upsert_asset(
            c, 42,
            key="assets/logo.png",
            src_url="https://x/logo.png",
        )
        body = c.put.call_args[0][1]
        assert body["asset"]["src"] == "https://x/logo.png"
        assert "value" not in body["asset"]

    def test_upsert_requires_exactly_one_of_value_src(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ThemeAssets.upsert_asset(
                c, 42, key="x", value="", src_url="",
            )
        with pytest.raises(ValueError):
            ThemeAssets.upsert_asset(
                c, 42, key="x", value="v", src_url="u",
            )

    def test_upsert_requires_key(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ThemeAssets.upsert_asset(c, 42, key="", value="v")

    def test_delete_asset(self):
        c = _fake_client()
        ThemeAssets.delete_asset(
            c, 42, key="snippets/stale.liquid",
        )
        params = c.delete.call_args[1]["params"]
        assert params["asset[key]"] == (
            "snippets/stale.liquid"
        )

    def test_delete_empty_key_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ThemeAssets.delete_asset(c, 42, key="")


# ── ShippingZones ────────────────────────────────────────


class TestShippingZones:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {"shipping_zones": [
            {"id": 1, "name": "US"},
            {"id": 2, "name": "EU"},
        ]}
        assert len(ShippingZones.list_zones(c)) == 2

    def test_list_zone_countries(self):
        c = _fake_client()
        c.get.return_value = {"shipping_zones": [
            {"id": 1, "countries": [
                {"code": "US"}, {"code": "CA"},
            ]},
            {"id": 2, "countries": [{"code": "GB"}]},
        ]}
        out = ShippingZones.list_zone_countries(c, 1)
        codes = [c["code"] for c in out]
        assert codes == ["US", "CA"]

    def test_covers_country_yes(self):
        c = _fake_client()
        c.get.return_value = {"shipping_zones": [
            {"id": 1, "countries": [{"code": "US"}]},
        ]}
        assert ShippingZones.covers_country(c, "us") is True

    def test_covers_country_no(self):
        c = _fake_client()
        c.get.return_value = {"shipping_zones": [
            {"id": 1, "countries": [{"code": "US"}]},
        ]}
        assert (
            ShippingZones.covers_country(c, "MN") is False
        )

    def test_covers_rest_of_world_wildcard(self):
        c = _fake_client()
        c.get.return_value = {"shipping_zones": [
            {"id": 1, "countries": [{"code": "*"}]},
        ]}
        assert (
            ShippingZones.covers_country(c, "XK") is True
        )

    def test_covers_empty_code_false(self):
        c = _fake_client()
        assert ShippingZones.covers_country(c, "") is False


# ── ShippingRates ────────────────────────────────────────


class TestPriceBasedRates:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {
            "price_based_shipping_rates": [{"id": 1}],
        }
        assert len(
            ShippingRates.list_price_based(c, 99),
        ) == 1

    def test_create_minimum(self):
        c = _fake_client()
        c.post.return_value = {
            "price_based_shipping_rate": {"id": 1},
        }
        ShippingRates.create_price_based(
            c, 99, name="Flat $6", price=6.0,
        )
        body = c.post.call_args[0][1]
        r = body["price_based_shipping_rate"]
        assert r["name"] == "Flat $6"
        assert r["price"] == "6.00"

    def test_create_free_over_threshold(self):
        c = _fake_client()
        c.post.return_value = {
            "price_based_shipping_rate": {"id": 1},
        }
        ShippingRates.create_price_based(
            c, 99, name="Free over $50",
            price=0, min_order_subtotal=50,
        )
        body = c.post.call_args[0][1]
        r = body["price_based_shipping_rate"]
        assert r["min_order_subtotal"] == "50.00"

    def test_create_empty_name_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ShippingRates.create_price_based(
                c, 99, name="", price=0,
            )

    def test_update(self):
        c = _fake_client()
        c.put.return_value = {
            "price_based_shipping_rate": {"id": 1},
        }
        ShippingRates.update_price_based(
            c, 99, 1, fields={"price": "7.00"},
        )
        body = c.put.call_args[0][1]
        r = body["price_based_shipping_rate"]
        assert r["id"] == 1
        assert r["price"] == "7.00"

    def test_update_empty_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ShippingRates.update_price_based(
                c, 99, 1, fields={},
            )

    def test_delete(self):
        c = _fake_client()
        ShippingRates.delete_price_based(c, 99, 1)
        c.delete.assert_called_once()


class TestWeightBasedRates:
    def test_create_kg_converted_in_body(self):
        c = _fake_client()
        c.post.return_value = {
            "weight_based_shipping_rate": {"id": 1},
        }
        ShippingRates.create_weight_based(
            c, 99,
            name="Light (0-0.5kg)", price=4.0,
            weight_low_kg=0.0, weight_high_kg=0.5,
        )
        body = c.post.call_args[0][1]
        r = body["weight_based_shipping_rate"]
        assert r["weight_low"] == "0.000"
        assert r["weight_high"] == "0.500"
        assert r["price"] == "4.00"

    def test_create_invalid_range_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ShippingRates.create_weight_based(
                c, 99, name="x", price=1,
                weight_low_kg=2.0, weight_high_kg=1.0,
            )

    def test_create_negative_low_raises(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            ShippingRates.create_weight_based(
                c, 99, name="x", price=1,
                weight_low_kg=-1.0, weight_high_kg=1.0,
            )

    def test_list_weight(self):
        c = _fake_client()
        c.get.return_value = {
            "weight_based_shipping_rates": [{"id": 1}],
        }
        assert len(
            ShippingRates.list_weight_based(c, 99),
        ) == 1

    def test_update_weight(self):
        c = _fake_client()
        c.put.return_value = {
            "weight_based_shipping_rate": {"id": 1},
        }
        ShippingRates.update_weight_based(
            c, 99, 1, fields={"price": "5.00"},
        )
        body = c.put.call_args[0][1]
        assert body["weight_based_shipping_rate"]["id"] == 1

    def test_delete_weight(self):
        c = _fake_client()
        ShippingRates.delete_weight_based(c, 99, 1)
        c.delete.assert_called_once()


# ── CarrierServices ──────────────────────────────────────


class TestCarrierServices:
    def test_list(self):
        c = _fake_client()
        c.get.return_value = {"carrier_services": [{"id": 1}]}
        assert len(CarrierServices.list_services(c)) == 1

    def test_get(self):
        c = _fake_client()
        c.get.return_value = {"carrier_service": {"id": 7}}
        assert CarrierServices.get(c, 7)["id"] == 7

    def test_get_missing_raises(self):
        c = _fake_client()
        c.get.return_value = {}
        with pytest.raises(ShopifyAdminError):
            CarrierServices.get(c, 7)

    def test_create_happy_path(self):
        c = _fake_client()
        c.post.return_value = {"carrier_service": {"id": 1}}
        CarrierServices.create(
            c,
            name="CJ Tracking",
            callback_url="https://api.shopai/cj-rates",
        )
        body = c.post.call_args[0][1]
        svc = body["carrier_service"]
        assert svc["name"] == "CJ Tracking"
        assert svc["callback_url"] == (
            "https://api.shopai/cj-rates"
        )
        assert svc["service_discovery"] is True

    def test_create_requires_both_args(self):
        c = _fake_client()
        with pytest.raises(ValueError):
            CarrierServices.create(
                c, name="", callback_url="https://x",
            )
        with pytest.raises(ValueError):
            CarrierServices.create(
                c, name="x", callback_url="",
            )

    def test_delete(self):
        c = _fake_client()
        CarrierServices.delete(c, 7)
        c.delete.assert_called_once()
