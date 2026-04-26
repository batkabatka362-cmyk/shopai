"""Tests for ``platforms.shopify.ShopifyAdapter``.

The adapter is a thin facade: it must

  * normalise scheme-prefixed shop URLs to bare hosts,
  * delegate reads to ``ShopifyAPI`` and translate their dict output
    into the same shape ``WooCommerceAdapter`` produces,
  * delegate writes to ``ProductUpdater`` only after credentials are
    set, and return an explicit error dict otherwise,
  * NEVER fabricate a mock response when the underlying client fails.

Real HTTP is forbidden — every test patches the inner client classes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from platforms.shopify import ShopifyAdapter, _normalize_shop_url, get_shopify
import platforms.shopify as shopify_mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "SHOPAI_SHOPIFY_URL",
        "SHOPAI_SHOPIFY_KEY",
        "SHOPAI_SHOPIFY_CLIENT_ID",
        "SHOPAI_SHOPIFY_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    # Reset module-level singleton between tests
    shopify_mod._instance = None
    yield
    shopify_mod._instance = None


# ── URL normalisation ───────────────────────────────────────────────


class TestNormalizeShopUrl:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("mystore.myshopify.com", "mystore.myshopify.com"),
            ("https://mystore.myshopify.com", "mystore.myshopify.com"),
            ("http://mystore.myshopify.com/", "mystore.myshopify.com"),
            ("  https://mystore.myshopify.com/  ", "mystore.myshopify.com"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalises_to_bare_host(self, raw, expected):
        assert _normalize_shop_url(raw) == expected


# ── Construction & configuration ────────────────────────────────────


class TestConstruction:
    def test_unconfigured_without_env_or_args(self):
        a = ShopifyAdapter()
        assert a.is_configured is False

    def test_picks_up_env_vars(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "https://envshop.myshopify.com/")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_env")
        a = ShopifyAdapter()
        assert a.is_configured is True
        # URL must have been normalised even from the env var.
        assert a.get_stats()["shop"] == "envshop.myshopify.com"

    def test_explicit_args_beat_env_vars(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "envshop.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_KEY", "shpat_env")
        a = ShopifyAdapter("https://argshop.myshopify.com/", "shpat_arg")
        assert a.get_stats()["shop"] == "argshop.myshopify.com"

    def test_configure_overwrites(self):
        a = ShopifyAdapter()
        a.configure("https://later.myshopify.com/", "shpat_later")
        assert a.is_configured is True
        assert a.get_stats()["shop"] == "later.myshopify.com"


# ── Reads — empty/error paths must NOT fabricate data ───────────────


class TestReadsWithoutCredentials:
    def test_get_products_returns_empty_when_unconfigured(self):
        assert ShopifyAdapter().get_products() == []

    def test_get_orders_returns_empty_when_unconfigured(self):
        assert ShopifyAdapter().get_orders() == []

    def test_get_customers_returns_empty_when_unconfigured(self):
        assert ShopifyAdapter().get_customers() == []


class TestReadsSwallowApiFailures:
    """If the underlying ShopifyAPI raises, the adapter must log and
    return ``[]`` — it must not propagate the error and it must not
    invent a fake fallback dataset."""

    def _adapter(self):
        return ShopifyAdapter("shop.myshopify.com", "shpat_x")

    def test_get_products_returns_empty_on_exception(self):
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_products.side_effect = RuntimeError("boom")
            assert self._adapter().get_products() == []

    def test_get_orders_returns_empty_on_exception(self):
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_orders.side_effect = RuntimeError("boom")
            assert self._adapter().get_orders() == []

    def test_get_customers_returns_empty_on_exception(self):
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_customers.side_effect = RuntimeError("boom")
            assert self._adapter().get_customers() == []


# ── Reads — happy paths normalise the Shopify payloads ──────────────


@pytest.fixture
def configured():
    return ShopifyAdapter("shop.myshopify.com", "shpat_x")


class TestProductNormalisation:
    def test_extracts_first_variant_fields(self, configured):
        raw = {
            "products": [
                {
                    "id": 12345,
                    "title": "Cool Mug",
                    "body_html": "<p>The mug.</p>",
                    "product_type": "Drinkware",
                    "vendor": "Acme",
                    "tags": "morning, coffee",
                    "images": [{"src": "https://cdn/mug.jpg"}],
                    "variants": [
                        {
                            "id": 999,
                            "price": "12.50",
                            "cost": "4.00",
                            "compare_at_price": "20.00",
                            "inventory_quantity": 7,
                        }
                    ],
                }
            ]
        }
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_products.return_value = raw
            result = configured.get_products()
        assert len(result) == 1
        p = result[0]
        assert p["id"] == "12345"
        assert p["name"] == "Cool Mug"
        assert p["price"] == 12.50
        assert p["cost"] == 4.0
        assert p["compare_at_price"] == 20.0
        assert p["inventory_quantity"] == 7
        assert p["category"] == "Drinkware"
        assert p["images"] == ["https://cdn/mug.jpg"]
        assert p["variant_id"] == "999"
        assert p["platform"] == "shopify"

    def test_handles_list_tags(self, configured):
        raw = {
            "products": [
                {"id": 1, "title": "T", "variants": [{"price": "1.00"}],
                 "tags": ["a", "b", "c"]}
            ]
        }
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_products.return_value = raw
            result = configured.get_products()
        assert result[0]["tags"] == "a, b, c"

    def test_handles_missing_variants(self, configured):
        raw = {"products": [{"id": 7, "title": "Bare", "variants": []}]}
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_products.return_value = raw
            result = configured.get_products()
        assert result[0]["price"] == 0.0
        assert result[0]["inventory_quantity"] == 0
        assert result[0]["variant_id"] == ""

    def test_respects_limit(self, configured):
        raw = {"products": [{"id": i, "title": f"P{i}", "variants": []} for i in range(10)]}
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_products.return_value = raw
            result = configured.get_products(limit=3)
        assert len(result) == 3
        assert [p["id"] for p in result] == ["0", "1", "2"]


class TestOrderNormalisation:
    def test_basic_order(self, configured):
        raw = {
            "orders": [
                {
                    "id": 555,
                    "total_price": "99.50",
                    "subtotal_price": "90.00",
                    "financial_status": "paid",
                    "fulfillment_status": None,
                    "customer": {"id": 42},
                    "line_items": [{}, {}, {}],
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ]
        }
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_orders.return_value = raw
            result = configured.get_orders()
        o = result[0]
        assert o["id"] == "555"
        assert o["total"] == 99.5
        assert o["subtotal"] == 90.0
        assert o["status"] == "paid"
        # Shopify returns null for un-fulfilled orders — must coerce to "".
        assert o["fulfillment_status"] == ""
        assert o["customer_id"] == "42"
        assert o["items"] == 3
        assert o["platform"] == "shopify"

    def test_passes_days_back_through(self, configured):
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_orders.return_value = {"orders": []}
            configured.get_orders(days_back=7)
            kwargs = MockAPI.return_value.fetch_orders.call_args.kwargs
            assert kwargs.get("days_back") == 7


class TestCustomerNormalisation:
    def test_concatenates_name(self, configured):
        raw = {
            "customers": [
                {
                    "id": 1,
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "email": "ada@example.com",
                    "orders_count": 4,
                    "total_spent": "123.45",
                    "created_at": "2025-05-01T00:00:00Z",
                }
            ]
        }
        with patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAPI.return_value.fetch_customers.return_value = raw
            result = configured.get_customers()
        c = result[0]
        assert c["id"] == "1"
        assert c["name"] == "Ada Lovelace"
        assert c["email"] == "ada@example.com"
        assert c["orders"] == 4
        assert c["total_spent"] == 123.45
        assert c["platform"] == "shopify"


# ── Writes ──────────────────────────────────────────────────────────


class TestWritesWithoutCredentials:
    def test_update_product_errors(self):
        out = ShopifyAdapter().update_product("1", {"title": "X"})
        assert out == {"status": "error", "error": "shopify_not_configured"}

    def test_update_price_errors(self):
        out = ShopifyAdapter().update_price("1", "2", 9.99)
        assert out == {"status": "error", "error": "shopify_not_configured"}

    def test_update_inventory_errors(self):
        out = ShopifyAdapter().update_inventory("1", "2", 5)
        assert out == {"status": "error", "error": "shopify_not_configured"}


class TestWritesDelegateToProductUpdater:
    def _adapter(self):
        return ShopifyAdapter("shop.myshopify.com", "shpat_x")

    def test_update_product_calls_updater(self):
        with patch("execution.shopify.product_updater.ProductUpdater") as MockUpdater:
            MockUpdater.return_value.update_product.return_value = {"status": "updated"}
            out = self._adapter().update_product("p1", {"title": "New"})
            MockUpdater.return_value.update_product.assert_called_once_with(
                "shop.myshopify.com", "shpat_x", "p1", {"title": "New"}
            )
            assert out == {"status": "updated"}

    def test_update_price_calls_updater(self):
        with patch("execution.shopify.product_updater.ProductUpdater") as MockUpdater:
            MockUpdater.return_value.update_price.return_value = {"status": "updated"}
            out = self._adapter().update_price("p1", "v9", 12.34)
            MockUpdater.return_value.update_price.assert_called_once_with(
                "shop.myshopify.com", "shpat_x", "p1", "v9", 12.34
            )
            assert out == {"status": "updated"}

    def test_update_inventory_calls_updater(self):
        with patch("execution.shopify.product_updater.ProductUpdater") as MockUpdater:
            MockUpdater.return_value.update_inventory.return_value = {"status": "updated"}
            out = self._adapter().update_inventory("ii1", "loc1", 7)
            MockUpdater.return_value.update_inventory.assert_called_once_with(
                "shop.myshopify.com", "shpat_x", "ii1", "loc1", 7
            )
            assert out == {"status": "updated"}


# ── Stats & singleton ──────────────────────────────────────────────


class TestStats:
    def test_unconfigured(self):
        s = ShopifyAdapter().get_stats()
        assert s == {"platform": "shopify", "configured": False, "shop": ""}

    def test_configured(self):
        s = ShopifyAdapter("https://x.myshopify.com", "shpat_x").get_stats()
        assert s == {"platform": "shopify", "configured": True, "shop": "x.myshopify.com"}


class TestSingleton:
    def test_get_shopify_returns_same_instance(self):
        a = get_shopify()
        b = get_shopify()
        assert a is b
        assert isinstance(a, ShopifyAdapter)


# ── Client-credentials integration (2026 Dev Dashboard flow) ─────────


class TestClientCredentialsAuth:
    """When client_id + client_secret are provided (instead of, or in
    addition to, a static ``shpat_`` token), the adapter must mint a
    rotating token via ``core.auth.shopify_auth.ShopifyAuth`` and pass
    it to the underlying ``ShopifyAPI`` / ``ProductUpdater``.
    """

    def test_is_configured_with_client_credentials_alone(self):
        a = ShopifyAdapter("shop.myshopify.com", client_id="cid", client_secret="cs")
        assert a.is_configured is True

    def test_is_configured_picks_up_env_client_credentials(self, monkeypatch):
        monkeypatch.setenv("SHOPAI_SHOPIFY_URL", "envshop.myshopify.com")
        monkeypatch.setenv("SHOPAI_SHOPIFY_CLIENT_ID", "envcid")
        monkeypatch.setenv("SHOPAI_SHOPIFY_CLIENT_SECRET", "envcs")
        a = ShopifyAdapter()
        assert a.is_configured is True

    def test_static_token_wins_over_client_credentials(self):
        a = ShopifyAdapter(
            "shop.myshopify.com",
            access_token="shpat_static",
            client_id="cid",
            client_secret="cs",
        )
        # _resolve_token must NOT instantiate ShopifyAuth when a static
        # token is present — pin that with a patched constructor that
        # would explode if called.
        with patch("core.auth.shopify_auth.ShopifyAuth", side_effect=AssertionError("must not be called")):
            assert a._resolve_token() == "shpat_static"

    def test_resolve_token_uses_shopify_auth_when_only_client_credentials(self):
        a = ShopifyAdapter("shop.myshopify.com", client_id="cid", client_secret="cs")
        with patch("core.auth.shopify_auth.ShopifyAuth") as MockAuth:
            MockAuth.return_value.get_token.return_value = "rotating_token_xyz"
            assert a._resolve_token() == "rotating_token_xyz"
            # ShopifyAuth must be constructed with the same shop URL +
            # credentials we configured the adapter with.
            MockAuth.assert_called_once_with("shop.myshopify.com", "cid", "cs")

    def test_resolve_token_returns_empty_when_unconfigured(self):
        assert ShopifyAdapter()._resolve_token() == ""

    def test_resolve_token_swallows_refresh_errors(self):
        a = ShopifyAdapter("shop.myshopify.com", client_id="cid", client_secret="cs")
        with patch("core.auth.shopify_auth.ShopifyAuth") as MockAuth:
            MockAuth.return_value.get_token.side_effect = RuntimeError("boom")
            # Must not raise; reads/writes downstream rely on getting "".
            assert a._resolve_token() == ""

    def test_get_products_passes_rotating_token_to_shopify_api(self):
        a = ShopifyAdapter("shop.myshopify.com", client_id="cid", client_secret="cs")
        with patch("core.auth.shopify_auth.ShopifyAuth") as MockAuth, \
             patch("data_pipeline.ingestion.api.shopify_api.ShopifyAPI") as MockAPI:
            MockAuth.return_value.get_token.return_value = "tok_minted"
            MockAPI.return_value.fetch_products.return_value = {"products": []}
            a.get_products()
            MockAPI.assert_called_once_with("shop.myshopify.com", "tok_minted")
            MockAPI.return_value.fetch_products.assert_called_once_with(
                "shop.myshopify.com", "tok_minted"
            )

    def test_writes_pass_rotating_token_to_updater(self):
        a = ShopifyAdapter("shop.myshopify.com", client_id="cid", client_secret="cs")
        with patch("core.auth.shopify_auth.ShopifyAuth") as MockAuth, \
             patch("execution.shopify.product_updater.ProductUpdater") as MockUp:
            MockAuth.return_value.get_token.return_value = "tok_v2"
            MockUp.return_value.update_price.return_value = {"status": "updated"}
            a.update_price("p1", "v1", 9.99)
            MockUp.return_value.update_price.assert_called_once_with(
                "shop.myshopify.com", "tok_v2", "p1", "v1", 9.99
            )

    def test_writes_error_when_token_refresh_fails(self):
        a = ShopifyAdapter("shop.myshopify.com", client_id="cid", client_secret="cs")
        with patch("core.auth.shopify_auth.ShopifyAuth") as MockAuth:
            MockAuth.return_value.get_token.side_effect = RuntimeError("boom")
            out = a.update_product("p1", {"title": "X"})
            assert out == {"status": "error", "error": "token_unavailable"}
