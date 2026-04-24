"""TikTok Shop write-path tests — create_product_draft + fetch_orders.

Paranoid-mode guardrail checks (§4b.G): verify the adapter
NEVER creates a published product — every path forces
``is_published=False``. Also verify HMAC signing covers the
serialised body on POST calls.
"""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from core.adapters.tiktok_shop import (
    TikTokShopAdapter,
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
        app_secret="s3cr3t",
        access_token="tok",
        shop_id="1234",
        http=MagicMock(),
        now_fn=lambda: 1_800_000_000,
    )
    defaults.update(kw)
    return TikTokShopAdapter(**defaults)


# ── Signer covers body ──────────────────────────────────────


class TestSignerBody(unittest.TestCase):
    def test_body_string_changes_signature(self):
        """HMAC includes the body — same params + different
        body = different signature. This is the contract
        _request depends on for POST calls."""
        base_params = {"a": "1", "b": "2"}
        sig_a = _sign_request(
            app_secret="s", path="/p",
            params=base_params, body='{"x":1}',
        )
        sig_b = _sign_request(
            app_secret="s", path="/p",
            params=base_params, body='{"x":2}',
        )
        self.assertNotEqual(sig_a, sig_b)


# ── create_product_draft ────────────────────────────────────


class TestCreateProductDraft(unittest.TestCase):
    def test_unconfigured_returns_empty(self):
        a = TikTokShopAdapter(
            app_key="", app_secret="", access_token="",
            shop_id="",
        )
        out = a.create_product_draft(
            title="x", description="y",
            category_id="c", price_usd=10, inventory=5,
        )
        self.assertEqual(out, "")
        self.assertIn("not configured", a.stats()["last_error"])

    def test_missing_title_returns_empty(self):
        a = _build()
        out = a.create_product_draft(
            title="", description="y",
            category_id="c", price_usd=10, inventory=5,
        )
        self.assertEqual(out, "")
        self.assertIn("required", a.stats()["last_error"])

    def test_non_numeric_price_rejected(self):
        a = _build()
        out = a.create_product_draft(
            title="t", description="y",
            category_id="c", price_usd="nope", inventory=5,
        )
        self.assertEqual(out, "")

    def test_zero_price_rejected(self):
        a = _build()
        out = a.create_product_draft(
            title="t", description="y",
            category_id="c", price_usd=0, inventory=5,
        )
        self.assertEqual(out, "")

    def test_negative_inventory_rejected(self):
        a = _build()
        out = a.create_product_draft(
            title="t", description="y",
            category_id="c", price_usd=10, inventory=-1,
        )
        self.assertEqual(out, "")

    def test_happy_path_always_creates_draft(self):
        """Hard guardrail: the body MUST have is_published=False
        regardless of what the caller tries to pass."""
        fake_http = MagicMock()
        fake_http.post.return_value = _resp(
            200,
            {
                "code": 0,
                "message": "ok",
                "data": {"product_id": "TT-P-999"},
            },
            text="{}",
        )
        a = _build(http=fake_http)

        product_id = a.create_product_draft(
            title="Mushroom Lamp",
            description="Calm & cozy glow",
            category_id="1234",
            price_usd=19.99,
            inventory=25,
            image_urls=["https://cdn/x.jpg"],
            sku="DGR-LAMP-1",
            weight_grams=450,
        )
        self.assertEqual(product_id, "TT-P-999")
        # Exactly one POST call.
        self.assertEqual(fake_http.post.call_count, 1)
        call = fake_http.post.call_args
        # URL hits the products endpoint.
        self.assertIn(
            "/product/202309/products",
            call[0][0],
        )
        # Body is JSON + is_published=False.
        sent = json.loads(call[1]["data"])
        self.assertEqual(sent["is_published"], False)
        self.assertEqual(sent["title"], "Mushroom Lamp")
        self.assertEqual(sent["category_id"], "1234")
        self.assertEqual(
            sent["skus"][0]["price"]["amount"], "19.99",
        )
        self.assertEqual(
            sent["skus"][0]["inventory"][0]["quantity"], 25,
        )
        self.assertEqual(
            sent["skus"][0]["seller_sku"], "DGR-LAMP-1",
        )
        self.assertEqual(
            sent["main_images"], [{"uri": "https://cdn/x.jpg"}],
        )
        self.assertEqual(
            sent["package_weight"]["unit"], "KILOGRAM",
        )

    def test_missing_product_id_returns_empty(self):
        fake_http = MagicMock()
        fake_http.post.return_value = _resp(
            200,
            {"code": 0, "message": "ok", "data": {}},
            text="{}",
        )
        a = _build(http=fake_http)
        out = a.create_product_draft(
            title="t", description="d",
            category_id="c", price_usd=5, inventory=1,
        )
        self.assertEqual(out, "")

    def test_api_error_code_returns_empty(self):
        fake_http = MagicMock()
        fake_http.post.return_value = _resp(
            200,
            {"code": 12345, "message": "nope"},
            text="{}",
        )
        a = _build(http=fake_http)
        out = a.create_product_draft(
            title="t", description="d",
            category_id="c", price_usd=5, inventory=1,
        )
        self.assertEqual(out, "")
        self.assertIn("12345", a.stats()["last_error"])


# ── fetch_orders ───────────────────────────────────────────


class TestFetchOrders(unittest.TestCase):
    def test_unconfigured_returns_empty(self):
        a = TikTokShopAdapter(
            app_key="", app_secret="", access_token="",
            shop_id="",
        )
        self.assertEqual(a.fetch_orders(), [])

    def test_happy_path(self):
        fake_http = MagicMock()
        fake_http.post.return_value = _resp(
            200,
            {
                "code": 0,
                "data": {
                    "orders": [
                        {
                            "id": "TTO-1",
                            "order_status": "UNPAID",
                            "buyer_email": "b@x.com",
                            "create_time": 1800000001,
                            "payment": {
                                "total_amount": "29.99",
                                "currency": "USD",
                            },
                            "line_items": [{
                                "sku_id": "SKU-1",
                                "product_id": "P-1",
                                "quantity": 2,
                                "original_price": "14.99",
                            }],
                        },
                        "malformed-row",
                        {
                            "id": "TTO-2",
                            "order_status": "AWAITING_SHIPMENT",
                        },
                    ],
                },
            },
            text="{}",
        )
        a = _build(http=fake_http)
        out = a.fetch_orders(order_status="UNPAID")
        self.assertEqual(len(out), 2)
        o1 = out[0]
        self.assertEqual(o1["order_id"], "TTO-1")
        self.assertEqual(o1["total_amount"], 29.99)
        self.assertEqual(o1["currency"], "USD")
        self.assertEqual(len(o1["line_items"]), 1)
        # Second order is minimal; defaults fill in.
        self.assertEqual(out[1]["order_id"], "TTO-2")
        self.assertEqual(out[1]["total_amount"], 0.0)

    def test_api_failure_returns_empty_list(self):
        fake_http = MagicMock()
        fake_http.post.return_value = _resp(
            status=500, text="server error",
        )
        a = _build(http=fake_http)
        self.assertEqual(a.fetch_orders(), [])
        self.assertIn("500", a.stats()["last_error"])

    def test_page_size_clamped(self):
        fake_http = MagicMock()
        fake_http.post.return_value = _resp(
            200, {"code": 0, "data": {"orders": []}},
            text="{}",
        )
        a = _build(http=fake_http)
        a.fetch_orders(order_status="PAID", page_size=9999)
        url = fake_http.post.call_args[0][0]
        self.assertIn("page_size=100", url)

    def test_status_uppercased(self):
        fake_http = MagicMock()
        fake_http.post.return_value = _resp(
            200, {"code": 0, "data": {"orders": []}},
            text="{}",
        )
        a = _build(http=fake_http)
        a.fetch_orders(order_status="paid")
        body = json.loads(
            fake_http.post.call_args[1]["data"],
        )
        self.assertEqual(body["order_status"], "PAID")


if __name__ == "__main__":
    unittest.main()
