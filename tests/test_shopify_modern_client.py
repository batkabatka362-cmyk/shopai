"""Tests for core.adapters.shopify.modern_client (C)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from core.adapters.shopify.modern_client import (
    ShopifyModernClient,
    ShopifyThrottleError,
    ThrottleState,
)


def _resp(status=200, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = payload or {}
    return r


def _client(
    *, http=None, sleep_fn=None, now_fn=None, **kw,
):
    return ShopifyModernClient(
        shop_url=kw.pop("shop_url", "demo.myshopify.com"),
        access_token=kw.pop(
            "access_token", "shpat_xxx",
        ),
        http=http,
        sleep_fn=sleep_fn or (lambda s: None),
        now_fn=now_fn or (lambda: 1_000_000.0),
        retries=kw.pop("retries", 3),
        **kw,
    )


class TestConfig(unittest.TestCase):
    def test_missing_shop_raises(self):
        with self.assertRaises(ValueError):
            ShopifyModernClient(
                shop_url="", access_token="tok",
            )

    def test_missing_token_raises(self):
        with self.assertRaises(ValueError):
            ShopifyModernClient(
                shop_url="s.myshopify.com",
                access_token="",
            )

    def test_negative_retries_rejected(self):
        with self.assertRaises(ValueError):
            ShopifyModernClient(
                shop_url="s",
                access_token="t",
                retries=-1,
            )


class TestExecute(unittest.TestCase):
    def test_blank_query_raises(self):
        http = MagicMock()
        c = _client(http=http)
        with self.assertRaises(ValueError):
            c.execute("")

    def test_happy_path_returns_payload(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200,
            payload={
                "data": {"product": {"id": "gid://x/1"}},
                "extensions": {
                    "cost": {
                        "throttleStatus": {
                            "currentlyAvailable": 95,
                            "maximumAvailable": 100,
                            "restoreRate": 50,
                        },
                    },
                },
            },
        )
        c = _client(http=http)
        out = c.execute("{ __typename }")
        self.assertIn("data", out)
        # Throttle updated from response
        self.assertEqual(
            c.throttle().current_available, 95,
        )

    def test_client_request_id_auto_injected(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"data": {}},
        )
        c = _client(http=http)
        c.execute("{ __typename }")
        body = json.loads(
            http.post.call_args.kwargs["data"],
        )
        self.assertIn(
            "clientRequestId", body["variables"],
        )

    def test_client_request_id_honours_caller(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"data": {}},
        )
        c = _client(http=http)
        c.execute(
            "{ __typename }",
            client_request_id="req-42",
        )
        body = json.loads(
            http.post.call_args.kwargs["data"],
        )
        self.assertEqual(
            body["variables"]["clientRequestId"], "req-42",
        )

    def test_header_access_token_present(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"data": {}},
        )
        c = _client(http=http)
        c.execute("{ __typename }")
        headers = http.post.call_args.kwargs["headers"]
        self.assertEqual(
            headers["X-Shopify-Access-Token"],
            "shpat_xxx",
        )

    def test_endpoint_has_api_version(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"data": {}},
        )
        c = _client(http=http)
        c.execute("{ __typename }")
        url = http.post.call_args.args[0]
        self.assertIn("/admin/api/2024-10/", url)


class TestRetry(unittest.TestCase):
    def test_429_retries_then_succeeds(self):
        http = MagicMock()
        http.post.side_effect = [
            _resp(429, text="rate"),
            _resp(429, text="rate"),
            _resp(200, payload={"data": {"ok": True}}),
        ]
        sleeps: list[float] = []
        c = _client(
            http=http,
            sleep_fn=lambda s: sleeps.append(s),
            retries=3,
        )
        out = c.execute("{ __typename }")
        self.assertEqual(out["data"]["ok"], True)
        self.assertEqual(http.post.call_count, 3)
        # Backoff doubles: 1, 2
        self.assertGreaterEqual(len(sleeps), 2)

    def test_retries_exhausted_raises(self):
        http = MagicMock()
        http.post.return_value = _resp(
            429, text="rate",
        )
        c = _client(
            http=http,
            retries=1,
        )
        with self.assertRaises(ShopifyThrottleError):
            c.execute("{ __typename }")
        self.assertEqual(http.post.call_count, 2)

    def test_400_falls_back_once(self):
        http = MagicMock()
        http.post.side_effect = [
            _resp(400, text="unknown version"),
            _resp(200, payload={"data": {"ok": True}}),
        ]
        c = _client(http=http)
        out = c.execute("{ __typename }")
        self.assertEqual(out["data"]["ok"], True)
        # First call uses 2024-10, second uses fallback
        first_url = http.post.call_args_list[0].args[0]
        second_url = http.post.call_args_list[1].args[0]
        self.assertIn("2024-10", first_url)
        self.assertIn("2024-07", second_url)

    def test_500_raises_throttle_error(self):
        http = MagicMock()
        http.post.return_value = _resp(
            500, text="boom",
        )
        c = _client(http=http, retries=0)
        with self.assertRaises(ShopifyThrottleError):
            c.execute("{ __typename }")

    def test_network_exception_retried(self):
        http = MagicMock()
        http.post.side_effect = [
            RuntimeError("conn reset"),
            _resp(200, payload={"data": {"ok": 1}}),
        ]
        c = _client(http=http, retries=2)
        out = c.execute("{ __typename }")
        self.assertEqual(out["data"]["ok"], 1)


class TestHelpers(unittest.TestCase):
    def test_query_product_builds_query(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"data": {"product": {}}},
        )
        c = _client(http=http)
        out = c.query_product(
            gid="gid://shopify/Product/1",
        )
        self.assertIn("data", out)
        body = json.loads(
            http.post.call_args.kwargs["data"],
        )
        self.assertIn("product(id:", body["query"])
        self.assertEqual(
            body["variables"]["id"],
            "gid://shopify/Product/1",
        )

    def test_query_product_blank_gid(self):
        http = MagicMock()
        c = _client(http=http)
        with self.assertRaises(ValueError):
            c.query_product(gid="")

    def test_product_set_uses_supplied_request_id(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={
                "data": {
                    "productSet": {
                        "product": {"id": "gid://1"},
                        "userErrors": [],
                    },
                },
            },
        )
        c = _client(http=http)
        c.product_set(
            product_input={"title": "Pet Feeder"},
            client_request_id="owner-req-7",
        )
        body = json.loads(
            http.post.call_args.kwargs["data"],
        )
        self.assertEqual(
            body["variables"]["clientRequestId"],
            "owner-req-7",
        )

    def test_product_set_blank_input(self):
        c = _client()
        with self.assertRaises(ValueError):
            c.product_set(product_input={})


class TestThrottleWait(unittest.TestCase):
    def test_wait_triggered_when_low(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200,
            payload={
                "data": {},
                "extensions": {
                    "cost": {
                        "throttleStatus": {
                            "currentlyAvailable": 2,
                            "maximumAvailable": 100,
                            "restoreRate": 50,
                        },
                    },
                },
            },
        )
        slept: list[float] = []
        c = _client(
            http=http,
            sleep_fn=lambda s: slept.append(s),
        )
        # Prime the throttle state to low
        c.execute("{ __typename }")
        # Next call with expected_cost=10 should force a wait
        c.execute(
            "{ __typename }",
            expected_cost=10.0,
        )
        self.assertTrue(
            any(s > 0 for s in slept),
        )


class TestStats(unittest.TestCase):
    def test_stats_shape(self):
        http = MagicMock()
        http.post.return_value = _resp(
            200, payload={"data": {}},
        )
        c = _client(http=http)
        c.execute("{ __typename }")
        s = c.stats()
        self.assertEqual(s["api_version"], "2024-10")
        self.assertEqual(s["calls"], 1)
        self.assertIn("throttle", s)


class TestThrottleDict(unittest.TestCase):
    def test_as_dict(self):
        t = ThrottleState(
            current_available=10,
            max_available=100,
            restore_rate=50,
            last_update_ts=1.0,
        )
        self.assertIn(
            "current_available", t.as_dict(),
        )


if __name__ == "__main__":
    unittest.main()
