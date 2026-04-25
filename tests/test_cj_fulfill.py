"""Tests for core.adapters.fulfillment.cj_fulfill."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from core.adapters.fulfillment.cj_fulfill import (
    CJFulfillAdapter,
    FulfillmentOrder,
    TrackingUpdate,
)


def _http(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload or {}
    return r


def _auth_ok():
    return _http(200, payload={
        "data": {"accessToken": "tok"},
    })


def _create_ok(order_id="cj-123"):
    return _http(200, payload={
        "code": 200,
        "data": {
            "orderId": order_id,
            "orderStatus": "pending",
        },
    })


class TestConfig(unittest.TestCase):
    def test_unavailable_without_creds(self):
        os.environ.pop("CJ_EMAIL", None)
        os.environ.pop("CJ_API_KEY", None)
        ad = CJFulfillAdapter()
        self.assertFalse(ad.is_available())

    def test_available_with_env(self):
        try:
            os.environ["CJ_EMAIL"] = "a@b.com"
            os.environ["CJ_API_KEY"] = "k"
            ad = CJFulfillAdapter()
            self.assertTrue(ad.is_available())
        finally:
            os.environ.pop("CJ_EMAIL", None)
            os.environ.pop("CJ_API_KEY", None)

    def test_available_with_explicit(self):
        ad = CJFulfillAdapter(
            email="a@b.com", api_key="k",
        )
        self.assertTrue(ad.is_available())


class TestPlaceOrder(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.ad = CJFulfillAdapter(
            email="a@b.com", api_key="k",
            http=self.client,
        )

    def _minimal_line_items(self):
        return [{"productId": "cj-1", "quantity": 1}]

    def test_unconfigured_noop(self):
        ad = CJFulfillAdapter(http=self.client)
        out = ad.place_order(
            shopify_order_number="100",
            shipping_address={},
            line_items=self._minimal_line_items(),
        )
        self.assertIsNone(out)
        self.assertIn(
            "not configured", ad.stats()["last_error"],
        )

    def test_blank_shopify_number(self):
        out = self.ad.place_order(
            shopify_order_number="",
            shipping_address={},
            line_items=self._minimal_line_items(),
        )
        self.assertIsNone(out)

    def test_empty_line_items(self):
        out = self.ad.place_order(
            shopify_order_number="100",
            shipping_address={},
            line_items=[],
        )
        self.assertIsNone(out)

    def test_happy_path_returns_order(self):
        # First post is auth, second is createOrder
        self.client.post.side_effect = [
            _auth_ok(), _create_ok("cj-999"),
        ]
        out = self.ad.place_order(
            shopify_order_number="100",
            shipping_address={"country": "US"},
            line_items=self._minimal_line_items(),
        )
        self.assertIsInstance(out, FulfillmentOrder)
        self.assertEqual(out.fulfillment_id, "cj-999")
        self.assertEqual(out.shopify_order_number, "100")
        self.assertEqual(out.status, "pending")

    def test_auth_failure_surfaces(self):
        self.client.post.return_value = _http(
            401, text="unauthorized",
        )
        out = self.ad.place_order(
            shopify_order_number="100",
            shipping_address={},
            line_items=self._minimal_line_items(),
        )
        self.assertIsNone(out)
        self.assertIn(
            "401",
            self.ad.stats()["last_error"],
        )

    def test_create_http_error_surfaces(self):
        self.client.post.side_effect = [
            _auth_ok(),
            _http(500, text="boom"),
        ]
        out = self.ad.place_order(
            shopify_order_number="100",
            shipping_address={},
            line_items=self._minimal_line_items(),
        )
        self.assertIsNone(out)
        self.assertIn(
            "500",
            self.ad.stats()["last_error"],
        )

    def test_empty_order_id_surfaces(self):
        self.client.post.side_effect = [
            _auth_ok(),
            _http(200, payload={
                "code": 200, "data": {"orderId": ""},
            }),
        ]
        out = self.ad.place_order(
            shopify_order_number="100",
            shipping_address={},
            line_items=self._minimal_line_items(),
        )
        self.assertIsNone(out)
        self.assertIn(
            "empty orderId",
            self.ad.stats()["last_error"],
        )

    def test_dedupe_by_shopify_number(self):
        self.client.post.side_effect = [
            _auth_ok(), _create_ok("cj-1"),
        ]
        first = self.ad.place_order(
            shopify_order_number="100",
            shipping_address={},
            line_items=self._minimal_line_items(),
        )
        # Second call returns cached result without a new HTTP
        second = self.ad.place_order(
            shopify_order_number="100",
            shipping_address={},
            line_items=self._minimal_line_items(),
        )
        self.assertIs(first, second)
        # Only 2 total post calls (1 auth + 1 create)
        self.assertEqual(
            self.client.post.call_count, 2,
        )

    def test_cj_rejection_surfaces(self):
        self.client.post.side_effect = [
            _auth_ok(),
            _http(200, payload={
                "code": 500,
                "message": "invalid product",
            }),
        ]
        out = self.ad.place_order(
            shopify_order_number="100",
            shipping_address={},
            line_items=self._minimal_line_items(),
        )
        self.assertIsNone(out)
        self.assertIn(
            "invalid product",
            self.ad.stats()["last_error"],
        )


class TestTracking(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.ad = CJFulfillAdapter(
            email="a@b.com", api_key="k",
            http=self.client,
        )

    def test_unconfigured_noop(self):
        ad = CJFulfillAdapter(http=self.client)
        out = ad.get_tracking(tracking_number="TRK1")
        self.assertIsNone(out)

    def test_blank_tracking_number(self):
        out = self.ad.get_tracking(tracking_number="")
        self.assertIsNone(out)

    def test_happy_path(self):
        self.client.post.return_value = _auth_ok()
        self.client.get.return_value = _http(
            200, payload={
                "data": {
                    "carrier": "USPS",
                    "status": "in_transit",
                    "trackingEvents": [
                        {"at": "2026-04-20", "note": "shipped"},
                    ],
                },
            },
        )
        out = self.ad.get_tracking(
            tracking_number="TRK1",
        )
        self.assertIsInstance(out, TrackingUpdate)
        self.assertEqual(out.carrier, "USPS")
        self.assertEqual(out.status, "in_transit")
        self.assertEqual(len(out.events), 1)

    def test_http_error(self):
        self.client.post.return_value = _auth_ok()
        self.client.get.return_value = _http(
            503, text="busy",
        )
        out = self.ad.get_tracking(
            tracking_number="TRK1",
        )
        self.assertIsNone(out)
        self.assertIn(
            "503", self.ad.stats()["last_error"],
        )


class TestListAndStats(unittest.TestCase):
    def test_list_orders_cap(self):
        client = MagicMock()
        # Use an iterator that always returns a fresh auth + create
        # for the first few then an auth failure we don't hit.
        def side_effect_post(url, **kw):
            if "getAccessToken" in url:
                return _auth_ok()
            return _create_ok(f"cj-{id(kw)}")
        client.post.side_effect = side_effect_post
        ad = CJFulfillAdapter(
            email="a@b.com", api_key="k",
            http=client,
        )
        for i in range(5):
            ad.place_order(
                shopify_order_number=f"ord-{i}",
                shipping_address={"country": "US"},
                line_items=[
                    {"productId": "cj-1", "quantity": 1},
                ],
            )
        self.assertEqual(len(ad.list_orders()), 5)

    def test_stats_shape(self):
        ad = CJFulfillAdapter(
            email="a@b.com", api_key="k",
        )
        s = ad.stats()
        self.assertTrue(s["configured"])
        self.assertFalse(s["has_token"])
        self.assertEqual(s["orders_placed"], 0)


class TestDict(unittest.TestCase):
    def test_order_dict(self):
        o = FulfillmentOrder(
            fulfillment_id="cj-1",
            shopify_order_number="ord-1",
            status="pending",
            created_at=1.0,
        )
        d = o.as_dict()
        self.assertEqual(d["fulfillment_id"], "cj-1")

    def test_tracking_dict(self):
        t = TrackingUpdate(
            tracking_number="TRK",
            carrier="USPS",
            status="in_transit",
            events=({"x": 1},),
            last_update_ts=1.0,
        )
        d = t.as_dict()
        self.assertEqual(d["carrier"], "USPS")


if __name__ == "__main__":
    unittest.main()
