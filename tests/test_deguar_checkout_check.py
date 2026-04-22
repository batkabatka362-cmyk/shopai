"""Tests for scripts/deguar_checkout_check.py."""
from __future__ import annotations

import urllib.error
from unittest.mock import patch

import pytest

from scripts import deguar_checkout_check as mod
from scripts._shopify_client import ShopifyClient


# ── analyse_zones ────────────────────────────────────────


class TestAnalyseZones:
    def test_no_zones(self):
        out = mod.analyse_zones([])
        assert out["total"] == 0
        assert out["good"] == []

    def test_healthy_zone(self):
        zones = [{
            "name": "Domestic",
            "countries": [{"code": "US"}, {"code": "CA"}],
            "price_based_shipping_rates": [
                {"price": "4.99"}, {"price": "9.99"},
            ],
            "weight_based_shipping_rates": [],
            "carrier_shipping_rate_providers": [],
        }]
        out = mod.analyse_zones(zones)
        assert len(out["good"]) == 1
        assert out["good"][0]["countries"] == ["US", "CA"]
        assert out["no_rate"] == []
        assert out["zero_rate"] == []

    def test_no_rates_flagged(self):
        zones = [{
            "name": "DeadZone",
            "countries": [{"code": "MN"}],
            "price_based_shipping_rates": [],
            "weight_based_shipping_rates": [],
            "carrier_shipping_rate_providers": [],
        }]
        out = mod.analyse_zones(zones)
        assert "DeadZone" in out["no_rate"]

    def test_zero_rates_flagged(self):
        zones = [{
            "name": "Freebies",
            "countries": [{"code": "US"}],
            "price_based_shipping_rates": [{"price": "0"}],
            "weight_based_shipping_rates": [],
            "carrier_shipping_rate_providers": [],
        }]
        out = mod.analyse_zones(zones)
        assert "Freebies" in out["zero_rate"]

    def test_carrier_rates_count_as_good(self):
        """Zone has no static rates but has a carrier-calculated
        provider (USPS/DHL live rates) — that's real shipping,
        not dead."""
        zones = [{
            "name": "Intl",
            "countries": [{"code": "XX"}],
            "price_based_shipping_rates": [],
            "weight_based_shipping_rates": [],
            "carrier_shipping_rate_providers": [
                {"id": 1, "carrier_service_id": 42},
            ],
        }]
        out = mod.analyse_zones(zones)
        assert len(out["good"]) == 1
        assert out["no_rate"] == []


# ── fetch_shipping_zones ────────────────────────────────


class TestFetchShippingZones:
    def test_returns_zones(self):
        with patch.object(
            ShopifyClient, "get",
            return_value={"shipping_zones": [{"name": "Z"}]},
        ):
            zones = mod.fetch_shipping_zones(
                ShopifyClient(url="x", token="t"),
            )
        assert len(zones) == 1

    def test_403_returns_empty(self):
        def boom(self, path):
            raise urllib.error.HTTPError(
                "u", 403, "Forbidden", None, None,
            )
        with patch.object(ShopifyClient, "get", boom):
            zones = mod.fetch_shipping_zones(
                ShopifyClient(url="x", token="t"),
            )
        assert zones == []


# ── _fetch_enabled_providers ────────────────────────────


class TestProviderFetch:
    def test_parses_providers(self):
        with patch.object(
            ShopifyClient, "get",
            return_value={"payments": [
                {"gateway": "shopify_payments", "enabled": True},
                {"gateway": "paypal", "enabled": False},
            ]},
        ):
            out = mod._fetch_enabled_providers(
                ShopifyClient(url="x", token="t"),
            )
        assert out == {
            "shopify_payments": True,
            "paypal": False,
        }

    def test_403_returns_empty(self):
        def boom(self, path):
            raise urllib.error.HTTPError(
                "u", 403, "Forbidden", None, None,
            )
        with patch.object(ShopifyClient, "get", boom):
            out = mod._fetch_enabled_providers(
                ShopifyClient(url="x", token="t"),
            )
        assert out == {}


# ── main() ──────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "x.myshopify.com")
    monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_good")


GOOD_ZONE = {
    "name": "Global",
    "countries": [{"code": "US"}, {"code": "MN"}],
    "price_based_shipping_rates": [{"price": "7.99"}],
    "weight_based_shipping_rates": [],
    "carrier_shipping_rate_providers": [],
}


class TestMain:
    def test_rc0_all_good(self, env, capsys):
        with patch.object(
            mod, "_fetch_enabled_providers",
            return_value={"shopify_payments": True},
        ), patch.object(
            mod, "fetch_shipping_zones", return_value=[GOOD_ZONE],
        ), patch.object(
            mod, "_probe_storefront_url",
            return_value=(200, ""),
        ):
            rc = mod.main([])
        assert rc == 0
        out = capsys.readouterr().out
        assert "READY" in out

    def test_rc2_no_payment_provider(self, env, capsys):
        with patch.object(
            mod, "_fetch_enabled_providers",
            return_value={"paypal": False},  # all disabled
        ), patch.object(
            mod, "fetch_shipping_zones", return_value=[GOOD_ZONE],
        ), patch.object(
            mod, "_probe_storefront_url",
            return_value=(200, ""),
        ):
            rc = mod.main([])
        assert rc == 2
        out = capsys.readouterr().out
        assert "no active payment provider" in out

    def test_rc2_no_shipping_zones(self, env, capsys):
        with patch.object(
            mod, "_fetch_enabled_providers",
            return_value={"paypal": True},
        ), patch.object(
            mod, "fetch_shipping_zones", return_value=[],
        ), patch.object(
            mod, "_probe_storefront_url",
            return_value=(200, ""),
        ):
            rc = mod.main([])
        assert rc == 2

    def test_rc2_when_home_unreachable(self, env, capsys):
        def probe(url):
            if url.endswith("/"):
                return (500, "HTTP 500")
            return (200, "")
        with patch.object(
            mod, "_fetch_enabled_providers",
            return_value={"paypal": True},
        ), patch.object(
            mod, "fetch_shipping_zones", return_value=[GOOD_ZONE],
        ), patch.object(mod, "_probe_storefront_url", probe):
            rc = mod.main([])
        assert rc == 2

    def test_rc1_when_zero_rate_only_warning(self, env):
        zero_zone = dict(GOOD_ZONE)
        zero_zone["price_based_shipping_rates"] = [{"price": "0"}]
        with patch.object(
            mod, "_fetch_enabled_providers",
            return_value={"paypal": True},
        ), patch.object(
            mod, "fetch_shipping_zones", return_value=[zero_zone],
        ), patch.object(
            mod, "_probe_storefront_url",
            return_value=(200, ""),
        ):
            rc = mod.main([])
        assert rc == 1

    def test_rc1_empty_checkout_404_is_warning(self, env):
        def probe(url):
            if url.endswith("/checkout"):
                return (404, "HTTP 404")
            return (200, "")
        with patch.object(
            mod, "_fetch_enabled_providers",
            return_value={"paypal": True},
        ), patch.object(
            mod, "fetch_shipping_zones", return_value=[GOOD_ZONE],
        ), patch.object(mod, "_probe_storefront_url", probe):
            rc = mod.main([])
        assert rc == 1  # warning, not blocker

    def test_env_missing_rc2(self, monkeypatch):
        monkeypatch.delenv("SHOPAI_SHOPIFY_URL", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_KEY", raising=False)
        monkeypatch.delenv("SHOPAI_SHOPIFY_TOKEN", raising=False)
        rc = mod.main([])
        assert rc == 2
