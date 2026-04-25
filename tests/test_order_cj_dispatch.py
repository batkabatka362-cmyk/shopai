"""Tests for the CJ fulfillment dispatch step of OrderWebhookHandler."""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from core.webhooks.order_handler import (
    OrderWebhookHandler,
    _shopify_lines_to_cj,
)


def _order(**overrides):
    data = {
        "id": "ord-123",
        "total_price": "49.99",
        "subtotal_price": "45.00",
        "line_items": [
            {
                "sku": "cj-product-1",
                "quantity": 2,
                "variant_id": "v1",
            },
        ],
        "shipping_address": {
            "name": "Jane Doe",
            "country": "US",
            "city": "Austin",
        },
        "customer": {"id": "c-1"},
    }
    data.update(overrides)
    return data


def _fake_cj(*, available=True, place_return=None,
             place_raise=None):
    adapter = MagicMock()
    adapter.is_available.return_value = available
    if place_raise is not None:
        adapter.place_order.side_effect = place_raise
    else:
        adapter.place_order.return_value = place_return
    adapter.stats.return_value = {"last_error": ""}
    return adapter


def _fulfillment_order(
    fulfillment_id="cj-999", status="pending",
):
    order = MagicMock()
    order.fulfillment_id = fulfillment_id
    order.status = status
    return order


class TestLineMapping(unittest.TestCase):
    def test_sku_prefix_maps(self):
        items = [
            {"sku": "cj-1", "quantity": 2},
            {"sku": "cj_2", "quantity": 1},
        ]
        out = _shopify_lines_to_cj(items)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["productId"], "cj-1")
        self.assertEqual(out[0]["quantity"], 2)

    def test_non_cj_sku_dropped(self):
        items = [
            {"sku": "internal-1", "quantity": 1},
            {"sku": "cj-x", "quantity": 1},
        ]
        out = _shopify_lines_to_cj(items)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["productId"], "cj-x")

    def test_properties_override(self):
        items = [{
            "sku": "internal-1",
            "quantity": 1,
            "properties": [
                {
                    "name": "cj_product_id",
                    "value": "cj-from-props",
                },
            ],
        }]
        out = _shopify_lines_to_cj(items)
        self.assertEqual(
            out[0]["productId"], "cj-from-props",
        )

    def test_variant_id_preserved(self):
        out = _shopify_lines_to_cj(
            [{
                "sku": "cj-1",
                "quantity": 1,
                "variant_id": "variant-9",
            }],
        )
        self.assertEqual(
            out[0]["variantId"], "variant-9",
        )

    def test_non_list_returns_empty(self):
        self.assertEqual(
            _shopify_lines_to_cj("not a list"), [],
        )

    def test_quantity_coerced(self):
        out = _shopify_lines_to_cj(
            [{"sku": "cj-1", "quantity": "3"}],
        )
        self.assertEqual(out[0]["quantity"], 3)


class TestDispatchGate(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.pop(
            "SHOPAI_ENABLE_CJ_FULFILL", None,
        )

    def tearDown(self):
        if self._orig is not None:
            os.environ[
                "SHOPAI_ENABLE_CJ_FULFILL"
            ] = self._orig

    def test_disabled_by_default(self):
        handler = OrderWebhookHandler(
            cj_fulfill_adapter=_fake_cj(),
        )
        result = handler.handle_order_paid(_order())
        self.assertEqual(
            result["cj_fulfillment"]["status"], "skipped",
        )
        self.assertEqual(
            result["cj_fulfillment"]["reason"], "disabled",
        )

    def test_enabled_unavailable_adapter_skips(self):
        os.environ["SHOPAI_ENABLE_CJ_FULFILL"] = "1"
        handler = OrderWebhookHandler(
            cj_fulfill_adapter=_fake_cj(available=False),
        )
        result = handler.handle_order_paid(_order())
        self.assertEqual(
            result["cj_fulfillment"]["status"], "skipped",
        )
        self.assertIn(
            "unavailable",
            result["cj_fulfillment"]["reason"],
        )

    def test_enabled_empty_line_items_skips(self):
        os.environ["SHOPAI_ENABLE_CJ_FULFILL"] = "1"
        adapter = _fake_cj(
            place_return=_fulfillment_order(),
        )
        handler = OrderWebhookHandler(
            cj_fulfill_adapter=adapter,
        )
        order = _order(line_items=[
            {"sku": "internal-only", "quantity": 1},
        ])
        result = handler.handle_order_paid(order)
        self.assertEqual(
            result["cj_fulfillment"]["status"], "skipped",
        )
        self.assertIn(
            "no mappable",
            result["cj_fulfillment"]["reason"],
        )
        adapter.place_order.assert_not_called()

    def test_happy_path_places_cj_order(self):
        os.environ["SHOPAI_ENABLE_CJ_FULFILL"] = "1"
        adapter = _fake_cj(
            place_return=_fulfillment_order(
                fulfillment_id="cj-777",
            ),
        )
        handler = OrderWebhookHandler(
            cj_fulfill_adapter=adapter,
        )
        result = handler.handle_order_paid(_order())
        self.assertEqual(
            result["cj_fulfillment"]["status"], "placed",
        )
        self.assertEqual(
            result["cj_fulfillment"]["fulfillment_id"],
            "cj-777",
        )
        adapter.place_order.assert_called_once()
        kwargs = adapter.place_order.call_args.kwargs
        self.assertEqual(
            kwargs["shopify_order_number"], "ord-123",
        )
        self.assertEqual(
            kwargs["shipping_address"]["country"], "US",
        )
        self.assertEqual(
            kwargs["line_items"][0]["productId"], "cj-1"
            if False else "cj-product-1",
        )

    def test_place_returns_none_marks_error(self):
        os.environ["SHOPAI_ENABLE_CJ_FULFILL"] = "1"
        adapter = _fake_cj(place_return=None)
        adapter.stats.return_value = {
            "last_error": "cj rate limit",
        }
        handler = OrderWebhookHandler(
            cj_fulfill_adapter=adapter,
        )
        result = handler.handle_order_paid(_order())
        self.assertEqual(
            result["cj_fulfillment"]["status"], "error",
        )
        self.assertIn(
            "rate limit",
            result["cj_fulfillment"]["reason"],
        )

    def test_place_exception_marks_error(self):
        os.environ["SHOPAI_ENABLE_CJ_FULFILL"] = "1"
        adapter = _fake_cj(
            place_raise=RuntimeError("boom"),
        )
        handler = OrderWebhookHandler(
            cj_fulfill_adapter=adapter,
        )
        result = handler.handle_order_paid(_order())
        self.assertEqual(
            result["cj_fulfillment"]["status"], "error",
        )
        self.assertIn(
            "boom",
            result["cj_fulfillment"]["reason"],
        )

    def test_existing_recorders_still_run(self):
        """The CJ wire-in must not break revenue / outcome /
        brain recording."""
        os.environ["SHOPAI_ENABLE_CJ_FULFILL"] = "1"
        handler = OrderWebhookHandler(
            cj_fulfill_adapter=_fake_cj(
                place_return=_fulfillment_order(),
            ),
        )
        result = handler.handle_order_paid(_order())
        self.assertIn("order_id", result)
        self.assertIn("revenue", result)
        self.assertIn("kpi_tracked", result)


if __name__ == "__main__":
    unittest.main()
