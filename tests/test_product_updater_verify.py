"""D2 tests — post_write_verifier wired into ProductUpdater."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from execution.shopify.product_updater import ProductUpdater


def _request_stub(responses):
    """Build a fake _make_request that returns responses in order
    per (method, url) key."""
    calls: list[dict] = []

    def _fake(method, url, headers, payload=None):
        calls.append({
            "method": method,
            "url": url,
            "payload": payload,
        })
        # pop the first matching response
        for i, r in enumerate(responses):
            if r["method"] == method and (
                r.get("url_contains") is None
                or r["url_contains"] in url
            ):
                responses.pop(i)
                return r["body"]
        raise AssertionError(
            f"unexpected request {method} {url}",
        )

    return _fake, calls


class TestProductUpdateVerify(unittest.TestCase):
    def test_update_product_verify_success_no_drift(self):
        u = ProductUpdater()
        responses = [
            {
                "method": "PUT",
                "url_contains": "/products/123.json",
                "body": {
                    "product": {
                        "id": 123, "title": "New Title",
                    },
                },
            },
            {
                "method": "GET",
                "url_contains": "/products/123.json",
                "body": {
                    "product": {
                        "id": 123, "title": "New Title",
                    },
                },
            },
        ]
        fake, calls = _request_stub(responses)
        with patch.object(u, "_make_request", side_effect=fake):
            res = u.update_product(
                "shop.myshopify.com", "tok", 123,
                {"title": "New Title"},
            )
        self.assertEqual(res["status"], "updated")
        self.assertNotIn("drift", res)
        methods = [c["method"] for c in calls]
        self.assertEqual(methods, ["PUT", "GET"])

    def test_update_product_verify_detects_drift(self):
        u = ProductUpdater()
        responses = [
            {
                "method": "PUT",
                "url_contains": "/products/123.json",
                "body": {
                    "product": {
                        "id": 123, "title": "Wanted",
                    },
                },
            },
            {
                "method": "GET",
                "url_contains": "/products/123.json",
                "body": {
                    # Shopify actually persisted a different title
                    "product": {
                        "id": 123, "title": "Shopify-mangled",
                    },
                },
            },
        ]
        fake, _ = _request_stub(responses)
        with patch.object(u, "_make_request", side_effect=fake):
            res = u.update_product(
                "shop.myshopify.com", "tok", 123,
                {"title": "Wanted"},
            )
        self.assertEqual(res["status"], "updated")
        self.assertIn("drift", res)
        self.assertTrue(res["drift"]["drift"])
        diff = res["drift"]["field_diffs"][0]
        self.assertEqual(diff["field"], "title")
        self.assertEqual(diff["expected"], "Wanted")
        self.assertEqual(
            diff["actual"], "Shopify-mangled",
        )

    def test_update_product_verify_opt_out(self):
        u = ProductUpdater()
        responses = [
            {
                "method": "PUT",
                "url_contains": "/products/123.json",
                "body": {
                    "product": {"id": 123, "title": "T"},
                },
            },
        ]
        fake, calls = _request_stub(responses)
        with patch.object(u, "_make_request", side_effect=fake):
            res = u.update_product(
                "shop.myshopify.com", "tok", 123,
                {"title": "T"},
                verify=False,
            )
        self.assertEqual(res["status"], "updated")
        self.assertNotIn("drift", res)
        self.assertEqual(
            [c["method"] for c in calls], ["PUT"],
        )

    def test_update_product_read_fail_marked_drift(self):
        u = ProductUpdater()

        def _fake(method, url, headers, payload=None):
            if method == "PUT":
                return {
                    "product": {"id": 1, "title": "x"},
                }
            raise RuntimeError("boom")

        with patch.object(u, "_make_request", side_effect=_fake):
            res = u.update_product(
                "s.myshopify.com", "tok", 1,
                {"title": "x"},
            )
        self.assertEqual(res["status"], "updated")
        self.assertIn("drift", res)
        self.assertFalse(res["drift"]["read_ok"])


class TestPriceVerify(unittest.TestCase):
    def test_update_price_no_drift_within_tolerance(self):
        u = ProductUpdater()
        responses = [
            {
                "method": "PUT",
                "url_contains": "/variants/555.json",
                "body": {
                    "variant": {"id": 555, "price": "29.99"},
                },
            },
            {
                "method": "GET",
                "url_contains": "/variants/555.json",
                "body": {
                    "variant": {
                        # 0.001 drift is inside the 0.01 tolerance
                        "id": 555, "price": "29.991",
                    },
                },
            },
        ]
        fake, _ = _request_stub(responses)
        with patch.object(u, "_make_request", side_effect=fake):
            res = u.update_price(
                "s.myshopify.com", "tok", 1, 555, 29.99,
            )
        self.assertEqual(res["status"], "updated")
        self.assertNotIn("drift", res)

    def test_update_price_drift_outside_tolerance(self):
        u = ProductUpdater()
        responses = [
            {
                "method": "PUT",
                "url_contains": "/variants/555.json",
                "body": {
                    "variant": {"id": 555, "price": "30.00"},
                },
            },
            {
                "method": "GET",
                "url_contains": "/variants/555.json",
                "body": {
                    "variant": {"id": 555, "price": "25.00"},
                },
            },
        ]
        fake, _ = _request_stub(responses)
        with patch.object(u, "_make_request", side_effect=fake):
            res = u.update_price(
                "s.myshopify.com", "tok", 1, 555, 30.00,
            )
        self.assertIn("drift", res)
        self.assertTrue(res["drift"]["drift"])


class TestDriftOutcomeEmission(unittest.TestCase):
    def test_drift_reports_to_engine_outcome_bus(self):
        u = ProductUpdater()
        responses = [
            {
                "method": "PUT",
                "url_contains": "/products/77.json",
                "body": {
                    "product": {"id": 77, "title": "A"},
                },
            },
            {
                "method": "GET",
                "url_contains": "/products/77.json",
                "body": {
                    "product": {"id": 77, "title": "B"},
                },
            },
        ]
        fake, _ = _request_stub(responses)

        reported = []

        class _FakeBus:
            def report(self, ev):
                reported.append(ev)

        with patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            return_value=_FakeBus(),
        ), patch.object(u, "_make_request", side_effect=fake):
            u.update_product(
                "s.myshopify.com", "tok", 77,
                {"title": "A"},
            )
        self.assertEqual(len(reported), 1)
        ev = reported[0]
        self.assertEqual(
            ev.engine, "shopify_product_updater",
        )
        self.assertEqual(ev.kpi, "execution_drift")
        self.assertFalse(ev.ok)


if __name__ == "__main__":
    unittest.main()
