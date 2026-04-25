"""Tests for A4 wire-in: OrderWebhookHandler → agentic channel attribution."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from core.webhooks.order_handler import OrderWebhookHandler


def _order(**overrides):
    data = {
        "id": "ord-42",
        "total_price": "30.00",
        "subtotal_price": "25.00",
        "line_items": [{"sku": "internal-1", "quantity": 1}],
        "customer": {"id": "c-1"},
        "source_name": "chatgpt",
    }
    data.update(overrides)
    return data


class TestAgenticAttribution(unittest.TestCase):
    def test_chatgpt_order_tagged(self):
        h = OrderWebhookHandler()
        out = h.handle_order_paid(_order())
        self.assertEqual(out.get("agentic_channel"), "chatgpt")

    def test_perplexity_order_tagged(self):
        h = OrderWebhookHandler()
        out = h.handle_order_paid(_order(
            source_name="perplexity",
        ))
        self.assertEqual(
            out.get("agentic_channel"), "perplexity",
        )

    def test_non_agentic_order_no_channel(self):
        h = OrderWebhookHandler()
        out = h.handle_order_paid(_order(
            source_name="web",
        ))
        self.assertNotIn("agentic_channel", out)

    def test_note_attribute_channel(self):
        h = OrderWebhookHandler()
        order = _order(source_name="")
        order["note_attributes"] = [
            {"name": "agentic_origin", "value": "copilot"},
        ]
        out = h.handle_order_paid(order)
        self.assertEqual(
            out.get("agentic_channel"), "copilot",
        )

    def test_bus_report_called_on_agentic_order(self):
        """Agentic order fires two bus reports: the
        agentic_storefront channel-level event (§4b wire) and
        the wider order_webhook event (audit batch 3 wire so
        organic orders also feed the learning ledger)."""
        fake_bus = MagicMock()
        with patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            return_value=fake_bus,
        ):
            h = OrderWebhookHandler()
            out = h.handle_order_paid(_order())
        self.assertTrue(out.get("agentic_bus_reported"))
        self.assertTrue(out.get("order_bus_reported"))
        self.assertEqual(fake_bus.report.call_count, 2)
        engines = [
            call.args[0].engine
            for call in fake_bus.report.call_args_list
        ]
        self.assertIn("agentic_storefront", engines)
        self.assertIn("order_webhook", engines)
        # agentic call still carries the channel-level shape
        agentic_call = next(
            call for call in fake_bus.report.call_args_list
            if call.args[0].engine == "agentic_storefront"
        )
        reported = agentic_call.args[0]
        self.assertEqual(reported.source, "chatgpt")
        self.assertEqual(reported.kpi, "gmv")
        self.assertAlmostEqual(reported.value, 30.0)

    def test_bus_report_on_non_agentic_order(self):
        """Organic (non-agentic) order still fires the wider
        order_webhook bus event so feedback_store + pattern
        miner receive signal (audit batch 3 wire-up)."""
        fake_bus = MagicMock()
        with patch(
            "core.integration.engine_outcome_bus"
            ".get_engine_outcome_bus",
            return_value=fake_bus,
        ):
            h = OrderWebhookHandler()
            out = h.handle_order_paid(_order(source_name="web"))
        # Only one emit (no agentic channel)
        self.assertEqual(fake_bus.report.call_count, 1)
        reported = fake_bus.report.call_args.args[0]
        self.assertEqual(reported.engine, "order_webhook")
        self.assertEqual(reported.source, "organic")
        self.assertTrue(out.get("order_bus_reported"))

    def test_classify_failure_is_soft(self):
        with patch(
            "core.bridge.agentic_storefront"
            ".AgenticStorefrontBridge.classify_order",
            side_effect=RuntimeError("boom"),
        ):
            h = OrderWebhookHandler()
            out = h.handle_order_paid(_order())
        self.assertNotIn("agentic_channel", out)
        self.assertTrue(out.get("kpi_tracked"))


if __name__ == "__main__":
    unittest.main()
