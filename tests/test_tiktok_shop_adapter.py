"""Tests for the TikTok Shop adapter (Z6 mission foundation)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.adapters.tiktok_shop import (
    TikTokShopAdapter,
    TikTokShopProduct,
    TikTokShopShopInfo,
    _sign_request,
)


def _resp(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload or {}
    return r


def _build(**kw):
    defaults = dict(
        app_key="ak",
        app_secret="as",
        access_token="tok",
        shop_id="1234",
        http=MagicMock(),
        now_fn=lambda: 1_800_000_000,
    )
    defaults.update(kw)
    return TikTokShopAdapter(**defaults)


class TestSigner(unittest.TestCase):
    def test_deterministic(self):
        sig = _sign_request(
            app_secret="s3cr3t",
            path="/x",
            params={"b": "2", "a": "1"},
        )
        sig2 = _sign_request(
            app_secret="s3cr3t",
            path="/x",
            params={"a": "1", "b": "2"},
        )
        self.assertEqual(sig, sig2)  # order-independent
        self.assertEqual(len(sig), 64)  # sha256 hex

    def test_excludes_sign_and_access_token(self):
        s1 = _sign_request(
            app_secret="s",
            path="/x",
            params={"a": "1"},
        )
        s2 = _sign_request(
            app_secret="s",
            path="/x",
            params={
                "a": "1",
                "sign": "abc",
                "access_token": "tok",
            },
        )
        self.assertEqual(s1, s2)

    def test_empty_secret_raises(self):
        with self.assertRaises(ValueError):
            _sign_request(
                app_secret="",
                path="/x",
                params={},
            )

    def test_body_affects_signature(self):
        s1 = _sign_request(
            app_secret="s",
            path="/x",
            params={"a": "1"},
        )
        s2 = _sign_request(
            app_secret="s",
            path="/x",
            params={"a": "1"},
            body='{"hi":1}',
        )
        self.assertNotEqual(s1, s2)


class TestConfig(unittest.TestCase):
    def test_is_available_all_required(self):
        a = _build()
        self.assertTrue(a.is_available())

    def test_is_available_missing_app_key(self):
        a = _build(app_key="")
        self.assertFalse(a.is_available())

    def test_is_available_missing_shop_id(self):
        a = _build(shop_id="")
        self.assertFalse(a.is_available())


class TestFetchShopInfo(unittest.TestCase):
    def test_returns_shop(self):
        http = MagicMock()
        http.get.return_value = _resp(
            payload={
                "code": 0,
                "data": {
                    "shops": [{
                        "id": "sh-1",
                        "name": "Pets Co",
                        "region": "US",
                        "status": "ACTIVE",
                    }],
                },
            },
        )
        a = _build(http=http)
        info = a.fetch_shop_info()
        self.assertIsInstance(info, TikTokShopShopInfo)
        self.assertEqual(info.shop_id, "sh-1")
        self.assertEqual(info.shop_name, "Pets Co")
        self.assertEqual(info.region, "US")

    def test_unconfigured_returns_none(self):
        a = _build(app_key="")
        self.assertIsNone(a.fetch_shop_info())
        self.assertIn(
            "not configured", a.stats()["last_error"],
        )

    def test_http_error_returns_none(self):
        http = MagicMock()
        http.get.return_value = _resp(
            status=401, text="unauthorized",
        )
        a = _build(http=http)
        self.assertIsNone(a.fetch_shop_info())
        self.assertIn("HTTP 401", a.stats()["last_error"])

    def test_api_error_code_returns_none(self):
        http = MagicMock()
        http.get.return_value = _resp(
            payload={
                "code": 10500,
                "message": "invalid signature",
            },
        )
        a = _build(http=http)
        self.assertIsNone(a.fetch_shop_info())
        self.assertIn("10500", a.stats()["last_error"])

    def test_empty_shops_list(self):
        http = MagicMock()
        http.get.return_value = _resp(
            payload={
                "code": 0,
                "data": {"shops": []},
            },
        )
        a = _build(http=http)
        self.assertIsNone(a.fetch_shop_info())

    def test_network_error_returns_none(self):
        http = MagicMock()
        http.get.side_effect = RuntimeError("down")
        a = _build(http=http)
        self.assertIsNone(a.fetch_shop_info())
        self.assertIn("network", a.stats()["last_error"])


class TestFetchProducts(unittest.TestCase):
    def test_returns_list(self):
        http = MagicMock()
        http.get.return_value = _resp(
            payload={
                "code": 0,
                "data": {
                    "products": [
                        {
                            "id": "p-1",
                            "title": "Pet Bowl",
                            "status": "LIVE",
                            "skus": [{
                                "price": {"sale_price": 29.99},
                            }],
                        },
                        {
                            "id": "p-2",
                            "title": "Cat Tree",
                            "status": "DRAFT",
                            "skus": [
                                {"price": {"sale_price": 70}},
                                {"price": {"sale_price": 90}},
                            ],
                        },
                    ],
                },
            },
        )
        a = _build(http=http)
        products = a.fetch_products(limit=10)
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0].product_id, "p-1")
        self.assertAlmostEqual(
            products[0].price_min, 29.99,
        )
        self.assertAlmostEqual(products[1].price_min, 70)
        self.assertAlmostEqual(products[1].price_max, 90)

    def test_limit_clamped(self):
        http = MagicMock()
        http.get.return_value = _resp(
            payload={
                "code": 0,
                "data": {"products": []},
            },
        )
        a = _build(http=http)
        a.fetch_products(limit=9999)
        call = http.get.call_args
        url = call[0][0] if call[0] else call.kwargs["url"]
        # 100 clamp
        self.assertIn("page_size=100", url)

    def test_malformed_products_skipped(self):
        http = MagicMock()
        http.get.return_value = _resp(
            payload={
                "code": 0,
                "data": {
                    "products": [
                        "not a dict",
                        {"id": "p-1", "title": "Ok"},
                    ],
                },
            },
        )
        a = _build(http=http)
        products = a.fetch_products()
        self.assertEqual(len(products), 1)

    def test_unconfigured_returns_empty(self):
        a = _build(access_token="")
        self.assertEqual(a.fetch_products(), [])


class TestSigningInLiveRequest(unittest.TestCase):
    def test_sign_included_in_url(self):
        http = MagicMock()
        http.get.return_value = _resp(
            payload={
                "code": 0,
                "data": {"shops": []},
            },
        )
        a = _build(http=http)
        a.fetch_shop_info()
        call = http.get.call_args
        url = call[0][0] if call[0] else call.kwargs["url"]
        self.assertIn("sign=", url)
        self.assertIn("app_key=ak", url)
        self.assertIn("shop_id=1234", url)


class TestStats(unittest.TestCase):
    def test_stats_shape(self):
        a = _build()
        s = a.stats()
        self.assertEqual(s["adapter"], "tiktok_shop")
        self.assertTrue(s["configured"])
        self.assertEqual(s["shop_id"], "1234")


if __name__ == "__main__":
    unittest.main()
