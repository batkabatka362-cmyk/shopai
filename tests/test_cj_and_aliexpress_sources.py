"""CJDropshipping + AliExpress source tests."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock

from agents.research.sources.cj_dropshipping import (
    CJDropshippingSource,
)
from agents.research.sources.aliexpress_scraper import (
    AliExpressScraperSource,
)


def _http_response(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    if payload is not None:
        r.json.return_value = payload
    r.text = text
    return r


# ── CJDropshipping ──────────────────────────────────────────


class TestCJConfig(unittest.TestCase):
    def test_unavailable_without_credentials(self):
        src = CJDropshippingSource()
        self.assertFalse(src.is_available())

    def test_available_with_env(self):
        try:
            os.environ["CJ_EMAIL"] = "x@y.com"
            os.environ["CJ_API_KEY"] = "secret"
            src = CJDropshippingSource()
            self.assertTrue(src.is_available())
        finally:
            os.environ.pop("CJ_EMAIL", None)
            os.environ.pop("CJ_API_KEY", None)

    def test_available_with_explicit_args(self):
        src = CJDropshippingSource(
            email="x@y.com", api_key="tok",
        )
        self.assertTrue(src.is_available())


class TestCJFetch(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.src = CJDropshippingSource(
            email="x@y.com",
            api_key="secret",
            http=self.client,
        )

    def test_unavailable_fetch_empty(self):
        unavail = CJDropshippingSource(http=self.client)
        self.assertEqual(unavail.fetch(), [])

    def test_auth_then_list(self):
        # auth response
        self.client.post.return_value = _http_response(
            200,
            payload={
                "data": {
                    "accessToken": "fake-token",
                },
            },
        )
        # list response
        self.client.get.return_value = _http_response(
            200,
            payload={
                "data": {
                    "list": [
                        {
                            "productId": "cj-1",
                            "productNameEn": (
                                "Pet Slow Feeder"
                            ),
                            "sellPrice": "8.50",
                            "productImage": "https://x",
                            "categoryName": "pet",
                            "listedNum": 100,
                        },
                        {
                            "productId": "cj-2",
                            "productNameEn": (
                                "Kitchen Gadget"
                            ),
                            "sellPrice": "12.00",
                            "productImage": "https://y",
                            "categoryName": "kitchen",
                            "listedNum": 50,
                        },
                    ],
                },
            },
        )
        out = self.src.fetch()
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].source, "cj_dropshipping")
        self.assertAlmostEqual(out[0].cost, 8.50)
        # retail = cost * margin_ratio(2.5) = 21.25
        self.assertAlmostEqual(out[0].price, 21.25)
        self.assertIn("pet", out[0].tags)

    def test_auth_failure_surfaces(self):
        self.client.post.return_value = _http_response(
            401, text="unauthorized",
        )
        out = self.src.fetch()
        self.assertEqual(out, [])
        self.assertIn(
            "401", self.src.stats()["last_error"],
        )

    def test_list_error_surfaces(self):
        self.client.post.return_value = _http_response(
            200,
            payload={
                "data": {"accessToken": "tok"},
            },
        )
        self.client.get.return_value = _http_response(
            500, text="server down",
        )
        out = self.src.fetch()
        self.assertEqual(out, [])
        self.assertIn(
            "500", self.src.stats()["last_error"],
        )

    def test_missing_title_skipped(self):
        self.client.post.return_value = _http_response(
            200,
            payload={
                "data": {"accessToken": "tok"},
            },
        )
        self.client.get.return_value = _http_response(
            200,
            payload={
                "data": {
                    "list": [
                        {"productId": "1"},   # no title
                        {
                            "productId": "2",
                            "productNameEn": "Good",
                            "sellPrice": "5",
                        },
                    ],
                },
            },
        )
        out = self.src.fetch()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Good")

    def test_token_cached(self):
        self.client.post.return_value = _http_response(
            200,
            payload={
                "data": {"accessToken": "tok"},
            },
        )
        self.client.get.return_value = _http_response(
            200, payload={"data": {"list": []}},
        )
        self.src.fetch()
        self.src.fetch()
        # Auth hit only once
        self.assertEqual(self.client.post.call_count, 1)


# ── AliExpressScraper ──────────────────────────────────────


class TestAliExpressConfig(unittest.TestCase):
    def setUp(self):
        os.environ.pop(
            "SHOPAI_ENABLE_ALIEXPRESS_SCRAPER", None,
        )

    def test_unavailable_without_env(self):
        src = AliExpressScraperSource()
        self.assertFalse(src.is_available())

    def test_available_with_env(self):
        try:
            os.environ[
                "SHOPAI_ENABLE_ALIEXPRESS_SCRAPER"
            ] = "1"
            src = AliExpressScraperSource()
            self.assertTrue(src.is_available())
        finally:
            os.environ.pop(
                "SHOPAI_ENABLE_ALIEXPRESS_SCRAPER",
                None,
            )

    def test_available_with_override(self):
        src = AliExpressScraperSource(
            enable_override=True,
        )
        self.assertTrue(src.is_available())


class TestAliExpressFetch(unittest.TestCase):
    def test_disabled_returns_empty(self):
        src = AliExpressScraperSource(
            enable_override=False,
        )
        self.assertEqual(src.fetch(), [])
        self.assertIn(
            "disabled",
            src.stats()["last_error"],
        )

    def test_no_html_returns_empty(self):
        client = MagicMock()
        client.get.return_value = _http_response(
            200, text="",
        )
        src = AliExpressScraperSource(
            enable_override=True,
            http=client,
        )
        self.assertEqual(src.fetch(), [])

    def test_runparams_parse(self):
        items_json = json.dumps({
            "mods": {
                "itemList": {
                    "content": [
                        {
                            "productId": "ali-1",
                            "title": {
                                "displayTitle": (
                                    "Pet Feeder"
                                ),
                            },
                            "image": {
                                "imgUrl": "https://x",
                            },
                            "prices": {
                                "salePrice": {
                                    "minPrice": 9.99,
                                },
                            },
                        },
                    ],
                },
            },
        })
        html = (
            "<html><script>window.runParams = "
            f"{items_json};"
            "</script></html>"
        )
        client = MagicMock()
        client.get.return_value = _http_response(
            200, text=html,
        )
        src = AliExpressScraperSource(
            enable_override=True,
            http=client,
        )
        out = src.fetch()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "Pet Feeder")
        self.assertAlmostEqual(out[0].price, 9.99)

    def test_http_error_surfaces(self):
        client = MagicMock()
        client.get.return_value = _http_response(
            503, text="busy",
        )
        src = AliExpressScraperSource(
            enable_override=True,
            http=client,
        )
        self.assertEqual(src.fetch(), [])
        self.assertIn(
            "503",
            src.stats()["last_error"],
        )

    def test_parse_failure_empty(self):
        # HTML with no runParams and no fallback match
        client = MagicMock()
        client.get.return_value = _http_response(
            200, text="<html>nothing</html>",
        )
        src = AliExpressScraperSource(
            enable_override=True,
            http=client,
        )
        out = src.fetch()
        self.assertEqual(out, [])
        self.assertIn(
            "no products parsed",
            src.stats()["last_error"],
        )


class TestStatsShape(unittest.TestCase):
    def test_cj_stats(self):
        src = CJDropshippingSource(
            email="x@y.com", api_key="tok",
        )
        s = src.stats()
        self.assertTrue(s["configured"])
        self.assertFalse(s["has_token"])

    def test_ali_stats(self):
        src = AliExpressScraperSource(
            enable_override=True,
        )
        s = src.stats()
        self.assertTrue(s["enabled"])
        self.assertTrue(s["experimental"])


if __name__ == "__main__":
    unittest.main()
