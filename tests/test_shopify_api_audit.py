"""Tests for audit-pass-43 fixes — defensive + real-bug
hardening in the Shopify API clients
(``data_pipeline.ingestion.api.shopify_api`` and
``shopify_graphql``).

These are the active-pull Shopify data sources (webhooks
pass 42 hardened the push side).

Real bugs fixed:

  * Double-scheme URL: ``f"https://{shop_url.rstrip('/')}/..."``
    produced ``https://https://mystore.myshopify.com/admin/...``
    when the caller passed a scheme-prefixed URL. Both the
    REST and GraphQL clients had the bug.

  * ``datetime.datetime.utcnow()`` is deprecated in Python
    3.12+ (DeprecationWarning → removal). Replaced with
    timezone-aware ``datetime.now(timezone.utc)``.

  * ``Retry-After`` header parsing: ``float(header)`` crashed
    on RFC 7231 HTTP-date form (e.g.
    ``"Wed, 21 Oct 2015 07:28:00 GMT"``). Now handles both
    delta-seconds and HTTP-date.

  * Missing ``requests`` library was silently treated as an
    empty successful fetch. Now raises ``ShopifyAPIError`` so
    the caller's except path records it in ``errors``.

  * ``ShopifyGraphQL.query`` had NO retry logic at all — any
    transient HTTP 5xx / 429 / network blip propagated
    immediately while the REST client retried three times.
    Audit pass 43 brings them to parity.

  * ``.get(k, {}).get(...)`` chains in every GraphQL
    normaliser crashed on present-but-None values — same
    bug class fixed in passes 32/36/40/41/42.

  * ``inv.get("quantities", [{}])[0].get("quantity")`` used
    a ``[{}]`` default but then crashed with IndexError /
    AttributeError if ``quantities`` was an explicit empty
    list or non-list dict.
"""
from __future__ import annotations

import datetime
import json
import urllib.error
from unittest import mock

import pytest

from data_pipeline.ingestion.api.shopify_api import (
    ShopifyAPI,
    ShopifyAPIError,
    _normalize_shop_url,
    _parse_retry_after,
)
from data_pipeline.ingestion.api.shopify_graphql import (
    ShopifyGraphQL,
    ShopifyGraphQLError,
)


# ═══════════════════════════════════════════════════════════
# URL normalization (double-scheme bug)
# ═══════════════════════════════════════════════════════════


class TestShopUrlNormalization:
    def test_bare_host(self):
        assert _normalize_shop_url("mystore.myshopify.com") == "mystore.myshopify.com"

    def test_strips_https_scheme(self):
        """Regression: pre-audit the client did
        ``f"https://{shop_url}/..."`` which produced
        ``https://https://...``."""
        assert _normalize_shop_url("https://mystore.myshopify.com") == "mystore.myshopify.com"

    def test_strips_http_scheme(self):
        assert _normalize_shop_url("http://mystore.myshopify.com") == "mystore.myshopify.com"

    def test_strips_trailing_slash(self):
        assert _normalize_shop_url("mystore.myshopify.com/") == "mystore.myshopify.com"
        assert _normalize_shop_url("https://mystore.myshopify.com/") == "mystore.myshopify.com"

    def test_none_returns_empty(self):
        assert _normalize_shop_url(None) == ""

    def test_non_string_returns_empty(self):
        assert _normalize_shop_url(42) == ""

    def test_rest_client_resolves_no_double_scheme(self):
        api = ShopifyAPI(shop_url="https://mystore.myshopify.com", api_key="tok")
        base, _ = api._resolve_credentials("", "")
        assert base == "https://mystore.myshopify.com/admin/api/2024-01"
        # Not https://https://
        assert base.count("https://") == 1

    def test_graphql_client_resolves_no_double_scheme(self):
        gql = ShopifyGraphQL("https://mystore.myshopify.com", "tok")
        assert gql._url == "https://mystore.myshopify.com/admin/api/2024-01/graphql.json"
        assert gql._url.count("https://") == 1


# ═══════════════════════════════════════════════════════════
# Retry-After header parsing
# ═══════════════════════════════════════════════════════════


class TestRetryAfterParsing:
    def test_delta_seconds(self):
        assert _parse_retry_after("5", 1.0) == 5.0
        assert _parse_retry_after("120", 1.0) == 120.0

    def test_http_date_past_falls_back(self):
        """Regression: pre-audit ``float("Wed, 21 Oct 2015 ...")``
        raised ValueError. Now we parse the date; if it's in
        the past we fall back rather than set a negative wait."""
        assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", 3.0) == 3.0

    def test_garbage_falls_back(self):
        assert _parse_retry_after("not a valid header", 2.5) == 2.5

    def test_empty_falls_back(self):
        assert _parse_retry_after("", 1.0) == 1.0

    def test_none_falls_back(self):
        assert _parse_retry_after(None, 1.0) == 1.0  # type: ignore[arg-type]

    def test_future_http_date(self):
        """A future HTTP-date should return the delta seconds."""
        future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=10)
        import email.utils
        header = email.utils.format_datetime(future)
        wait = _parse_retry_after(header, 999.0)
        # Should be close to 10 (allow some drift).
        assert 5.0 < wait <= 15.0


# ═══════════════════════════════════════════════════════════
# Missing requests library
# ═══════════════════════════════════════════════════════════


class TestMissingRequestsLibrary:
    def test_paginate_raises_when_requests_unavailable(self, monkeypatch):
        """Regression: pre-audit this silently returned []."""
        import data_pipeline.ingestion.api.shopify_api as mod
        monkeypatch.setattr(mod, "_REQUESTS_AVAILABLE", False)
        api = ShopifyAPI(shop_url="x.myshopify.com", api_key="t")
        result = api.fetch_products()
        # Error should propagate into the errors list.
        assert result["errors"]
        assert "requests" in result["errors"][0].lower()
        assert result["total"] == 0


# ═══════════════════════════════════════════════════════════
# fetch_orders uses timezone-aware UTC
# ═══════════════════════════════════════════════════════════


class TestFetchOrdersDatetime:
    def test_no_deprecated_utcnow_warning(self, monkeypatch, recwarn):
        """Regression: ``datetime.datetime.utcnow()`` emits
        DeprecationWarning in Python 3.12+."""
        import data_pipeline.ingestion.api.shopify_api as mod
        monkeypatch.setattr(mod, "_REQUESTS_AVAILABLE", False)
        api = ShopifyAPI(shop_url="x.myshopify.com", api_key="t")
        api.fetch_orders(days_back=7)  # hits the datetime path
        deprecations = [
            w for w in recwarn.list if issubclass(w.category, DeprecationWarning)
        ]
        # There may be unrelated deprecation warnings from test infra,
        # but none should mention ``utcnow``.
        utcnow_warnings = [
            w for w in deprecations if "utcnow" in str(w.message).lower()
        ]
        assert not utcnow_warnings

    def test_invalid_days_back_coerced(self, monkeypatch):
        import data_pipeline.ingestion.api.shopify_api as mod
        monkeypatch.setattr(mod, "_REQUESTS_AVAILABLE", False)
        api = ShopifyAPI(shop_url="x.myshopify.com", api_key="t")
        # Should not crash on negative / non-int days_back.
        r1 = api.fetch_orders(days_back=-5)
        r2 = api.fetch_orders(days_back="30")  # type: ignore[arg-type]
        assert "orders" in r1
        assert "orders" in r2


# ═══════════════════════════════════════════════════════════
# ShopifyGraphQL query retry + error handling
# ═══════════════════════════════════════════════════════════


class TestGraphQLRetry:
    def _make_resp(self, body: bytes):
        """Build a fake urlopen context manager."""
        class _Resp:
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
            def read(self_inner): return body
        return _Resp()

    def test_query_retries_on_5xx(self, monkeypatch):
        """Regression: pre-audit there was NO retry logic."""
        call_count = [0]
        good_body = json.dumps({"data": {"ok": True}}).encode()

        def fake_urlopen(req, timeout=30):
            call_count[0] += 1
            if call_count[0] < 3:
                raise urllib.error.HTTPError(
                    req.full_url, 500, "Server Error", {}, None  # type: ignore[arg-type]
                )
            return TestGraphQLRetry._make_resp(self=None, body=good_body)  # type: ignore[arg-type]

        # The above trick doesn't work; use the bound method via a helper instance.
        t = TestGraphQLRetry()

        def fake_urlopen2(req, timeout=30):
            call_count[0] += 1
            if call_count[0] < 3:
                raise urllib.error.HTTPError(
                    req.full_url, 500, "Server Error", {}, None  # type: ignore[arg-type]
                )
            return t._make_resp(good_body)

        monkeypatch.setattr(
            "data_pipeline.ingestion.api.shopify_graphql.urllib.request.urlopen",
            fake_urlopen2,
        )
        # Make sleep a no-op so the test is fast.
        monkeypatch.setattr(
            "data_pipeline.ingestion.api.shopify_graphql.time.sleep",
            lambda *a, **k: None,
        )
        gql = ShopifyGraphQL("x.myshopify.com", "t")
        result = gql.query("{ test }", max_retries=3, retry_delay=0.01)
        assert call_count[0] == 3
        assert result == {"data": {"ok": True}}

    def test_query_retries_on_429(self, monkeypatch):
        call_count = [0]
        t = TestGraphQLRetry()
        good_body = json.dumps({"data": {"ok": True}}).encode()

        def fake_urlopen(req, timeout=30):
            call_count[0] += 1
            if call_count[0] < 2:
                raise urllib.error.HTTPError(
                    req.full_url, 429, "Too Many", {}, None  # type: ignore[arg-type]
                )
            return t._make_resp(good_body)

        monkeypatch.setattr(
            "data_pipeline.ingestion.api.shopify_graphql.urllib.request.urlopen",
            fake_urlopen,
        )
        monkeypatch.setattr(
            "data_pipeline.ingestion.api.shopify_graphql.time.sleep",
            lambda *a, **k: None,
        )
        gql = ShopifyGraphQL("x.myshopify.com", "t")
        result = gql.query("{ test }", retry_delay=0.01)
        assert call_count[0] == 2
        assert result == {"data": {"ok": True}}

    def test_query_does_not_retry_on_4xx(self, monkeypatch):
        """Client errors (401, 403, 404) are not retryable."""
        call_count = [0]

        def fake_urlopen(req, timeout=30):
            call_count[0] += 1
            raise urllib.error.HTTPError(
                req.full_url, 401, "Unauthorized", {}, None  # type: ignore[arg-type]
            )

        monkeypatch.setattr(
            "data_pipeline.ingestion.api.shopify_graphql.urllib.request.urlopen",
            fake_urlopen,
        )
        monkeypatch.setattr(
            "data_pipeline.ingestion.api.shopify_graphql.time.sleep",
            lambda *a, **k: None,
        )
        gql = ShopifyGraphQL("x.myshopify.com", "t")
        with pytest.raises(ShopifyGraphQLError):
            gql.query("{ test }")
        # Only one attempt — no retry on 401.
        assert call_count[0] == 1

    def test_query_empty_graphql_rejected(self, monkeypatch):
        gql = ShopifyGraphQL("x.myshopify.com", "t")
        with pytest.raises(ShopifyGraphQLError):
            gql.query("")
        with pytest.raises(ShopifyGraphQLError):
            gql.query(None)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════
# GraphQL normalizers (present-but-None crashes)
# ═══════════════════════════════════════════════════════════


class TestGraphQLNormalizers:
    def test_normalize_product_none_node(self):
        assert ShopifyGraphQL._normalize_product(None) == {}

    def test_normalize_product_none_variants(self):
        """Regression: ``node.get("variants", {}).get("edges", [])``
        crashed on ``variants: null``."""
        result = ShopifyGraphQL._normalize_product({
            "id": "gid://shopify/Product/1",
            "title": "Test",
            "variants": None,
            "images": None,
        })
        assert result["id"] == "1"
        assert result["variants"] == []
        assert result["images"] == []

    def test_normalize_product_none_variant_inventory_item(self):
        result = ShopifyGraphQL._normalize_product({
            "id": "gid://shopify/Product/1",
            "variants": {
                "edges": [
                    {"node": {"id": "v1", "price": "5.00", "inventoryItem": None}},
                ],
            },
        })
        assert result["variants"][0]["price"] == 5.0
        assert result["variants"][0]["cost"] == 0.0

    def test_normalize_product_non_numeric_price_does_not_crash(self):
        """Pre-audit ``float(v.get("price", 0) or 0)`` crashed
        on non-numeric strings."""
        result = ShopifyGraphQL._normalize_product({
            "id": "gid://shopify/Product/1",
            "variants": {
                "edges": [
                    {"node": {"price": "N/A", "inventoryQuantity": "bad"}},
                ],
            },
        })
        assert result["variants"][0]["price"] == 0.0
        assert result["variants"][0]["inventory_quantity"] == 0

    def test_normalize_product_none_status(self):
        """Pre-audit ``node.get("status", "").lower()`` crashed
        on ``status: null``."""
        result = ShopifyGraphQL._normalize_product({
            "id": "gid://shopify/Product/1",
            "status": None,
        })
        assert result["status"] == ""

    def test_normalize_order_none_node(self):
        assert ShopifyGraphQL._normalize_order(None) == {}

    def test_normalize_order_missing_price_sets(self):
        """Regression: ``node.get("totalPriceSet", {}).get(...)``
        crashed when totalPriceSet was present-but-None."""
        result = ShopifyGraphQL._normalize_order({
            "id": "gid://shopify/Order/1",
            "totalPriceSet": None,
            "subtotalPriceSet": None,
            "customer": None,
            "lineItems": None,
        })
        assert result["id"] == "1"
        assert result["total"] == 0.0
        assert result["customer_id"] == ""
        assert result["items"] == 0

    def test_normalize_order_null_customer(self):
        """Guest orders have ``customer: null``."""
        result = ShopifyGraphQL._normalize_order({
            "id": "gid://shopify/Order/1",
            "customer": None,
        })
        assert result["customer_id"] == ""
        assert result["customer_email"] == ""

    def test_normalize_customer_none_node(self):
        assert ShopifyGraphQL._normalize_customer(None) == {}

    def test_normalize_customer_none_names(self):
        """Pre-audit the f-string produced ``"None None"``."""
        result = ShopifyGraphQL._normalize_customer({
            "id": "gid://shopify/Customer/1",
            "firstName": None,
            "lastName": None,
        })
        assert result["name"] == ""

    def test_normalize_customer_non_numeric_spent(self):
        result = ShopifyGraphQL._normalize_customer({
            "id": "gid://shopify/Customer/1",
            "amountSpent": {"amount": "not a number"},
            "numberOfOrders": "5",
        })
        assert result["total_spent"] == 0.0
        assert result["orders"] == 5


# ═══════════════════════════════════════════════════════════
# GraphQL extensions / cost tracking
# ═══════════════════════════════════════════════════════════


class TestGraphQLCostTracking:
    def test_none_extensions_does_not_crash(self, monkeypatch):
        """Regression: ``data.get("extensions", {}).get("cost", {})``
        crashed on ``extensions: null``."""
        body = json.dumps({"data": {"ok": True}, "extensions": None}).encode()

        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return body

        monkeypatch.setattr(
            "data_pipeline.ingestion.api.shopify_graphql.urllib.request.urlopen",
            lambda req, timeout=30: _Resp(),
        )
        gql = ShopifyGraphQL("x.myshopify.com", "t")
        result = gql.query("{ test }")
        assert result["data"] == {"ok": True}
        assert gql._cost_used == 0
