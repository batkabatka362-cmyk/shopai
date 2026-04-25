"""Tests for core.bridge.agentic_storefront (Wave B-1)."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.bridge.agentic_storefront import (
    AgenticStorefrontBridge,
    ChannelMetrics,
    ChannelStatus,
    get_agentic_bridge,
    normalize_source,
    reset_agentic_bridge_for_tests,
)


class TestNormalize(unittest.TestCase):
    def test_known_channels(self):
        for c in (
            "chatgpt", "perplexity", "copilot",
            "gemini", "agentic",
        ):
            self.assertEqual(normalize_source(c), c)

    def test_uppercase(self):
        self.assertEqual(
            normalize_source("ChatGPT"), "chatgpt",
        )

    def test_prefixed_tag(self):
        self.assertEqual(
            normalize_source("ai_agent:chatgpt"), "chatgpt",
        )

    def test_suffixed_tag(self):
        self.assertEqual(
            normalize_source("perplexity_web"), "perplexity",
        )

    def test_unknown_returns_blank(self):
        self.assertEqual(
            normalize_source("web"), "",
        )

    def test_empty_returns_blank(self):
        self.assertEqual(normalize_source(""), "")


class TestStatus(unittest.TestCase):
    def _mkclient(self, edges):
        c = MagicMock()
        c.execute.return_value = {
            "data": {
                "agenticStorefrontChannels": {
                    "edges": edges,
                },
            },
        }
        return c

    def test_no_client_returns_unknown_status(self):
        b = AgenticStorefrontBridge()
        out = b.status()
        self.assertEqual(len(out), 5)
        for s in out:
            self.assertFalse(s.enabled)
            self.assertIn("no graphql", s.note)

    def test_graphql_exception_degrades_to_unknown(self):
        c = MagicMock()
        c.execute.side_effect = RuntimeError("net")
        b = AgenticStorefrontBridge(graphql_client=c)
        out = b.status()
        self.assertEqual(len(out), 5)
        self.assertTrue(
            all("graphql error" in s.note for s in out),
        )

    def test_returned_channels_populated(self):
        c = self._mkclient([
            {"node": {
                "channelName": "chatgpt",
                "enabled": True,
                "lastAttributedOrderAt": 1000.0,
                "totalOrderCount": 42,
            }},
            {"node": {
                "channelName": "perplexity",
                "enabled": False,
                "totalOrderCount": 0,
            }},
        ])
        b = AgenticStorefrontBridge(graphql_client=c)
        out = b.status()
        self.assertEqual(len(out), 5)
        chatgpt = next(s for s in out if s.channel == "chatgpt")
        self.assertTrue(chatgpt.enabled)
        self.assertEqual(chatgpt.total_orders, 42)
        perplexity = next(
            s for s in out if s.channel == "perplexity"
        )
        self.assertFalse(perplexity.enabled)

    def test_missing_channels_marked_unreported(self):
        c = self._mkclient([])
        b = AgenticStorefrontBridge(graphql_client=c)
        out = b.status()
        for s in out:
            self.assertIn("not reported", s.note)

    def test_cached_for_5min(self):
        c = self._mkclient([{"node": {
            "channelName": "chatgpt", "enabled": True,
        }}])
        now = [1000.0]
        b = AgenticStorefrontBridge(
            graphql_client=c,
            now_fn=lambda: now[0],
        )
        b.status()
        now[0] += 100
        b.status()
        self.assertEqual(c.execute.call_count, 1)

    def test_force_bypasses_cache(self):
        c = self._mkclient([{"node": {
            "channelName": "chatgpt", "enabled": True,
        }}])
        b = AgenticStorefrontBridge(graphql_client=c)
        b.status()
        b.status(force=True)
        self.assertEqual(c.execute.call_count, 2)


class TestClassifyOrder(unittest.TestCase):
    def test_source_name_hit(self):
        self.assertEqual(
            AgenticStorefrontBridge.classify_order(
                {"source_name": "chatgpt"},
            ),
            "chatgpt",
        )

    def test_non_agentic_order(self):
        self.assertEqual(
            AgenticStorefrontBridge.classify_order(
                {"source_name": "online_store"},
            ),
            "",
        )

    def test_missing_source(self):
        self.assertEqual(
            AgenticStorefrontBridge.classify_order({}),
            "",
        )

    def test_non_dict_returns_blank(self):
        self.assertEqual(
            AgenticStorefrontBridge.classify_order(
                "not a dict",
            ),
            "",
        )

    def test_note_attribute_fallback(self):
        order = {
            "source_name": "web",
            "note_attributes": [
                {
                    "name": "agentic_source",
                    "value": "perplexity",
                },
            ],
        }
        self.assertEqual(
            AgenticStorefrontBridge.classify_order(order),
            "perplexity",
        )


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.b = AgenticStorefrontBridge(
            now_fn=lambda: 1_000_000.0,
        )

    def test_empty_orders(self):
        self.assertEqual(self.b.aggregate([]), [])

    def test_rolls_up_by_channel(self):
        orders = [
            {
                "source_name": "chatgpt",
                "total_price": 30.0,
                "created_at_ts": 1_000_000.0,
            },
            {
                "source_name": "chatgpt",
                "total_price": 50.0,
                "created_at_ts": 999_995.0,
            },
            {
                "source_name": "perplexity",
                "total_price": 20.0,
                "created_at_ts": 999_990.0,
            },
            {
                "source_name": "online_store",
                "total_price": 99.0,
                "created_at_ts": 999_990.0,
            },
        ]
        out = self.b.aggregate(orders)
        self.assertEqual(len(out), 2)
        chatgpt = next(m for m in out if m.channel == "chatgpt")
        self.assertEqual(chatgpt.orders, 2)
        self.assertAlmostEqual(chatgpt.gmv_usd, 80.0)
        self.assertAlmostEqual(chatgpt.aov_usd, 40.0)

    def test_window_days_filters_old(self):
        # Use a "now" large enough that 20-days-old ts stays
        # positive (the module treats ts<=0 as "unknown, keep").
        b = AgenticStorefrontBridge(
            now_fn=lambda: 10_000_000.0,
        )
        old_ts = 10_000_000.0 - 20 * 86400.0
        orders = [
            {
                "source_name": "chatgpt",
                "total_price": 10.0,
                "created_at_ts": old_ts,
            },
            {
                "source_name": "chatgpt",
                "total_price": 100.0,
                "created_at_ts": 10_000_000.0,
            },
        ]
        out = b.aggregate(orders, window_days=7)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(
            out[0].gmv_usd, 100.0,
        )

    def test_sorted_by_gmv_desc(self):
        orders = [
            {
                "source_name": "perplexity",
                "total_price": 200.0,
                "created_at_ts": 1_000_000.0,
            },
            {
                "source_name": "chatgpt",
                "total_price": 500.0,
                "created_at_ts": 1_000_000.0,
            },
        ]
        out = self.b.aggregate(orders)
        self.assertEqual(out[0].channel, "chatgpt")

    def test_invalid_total_price_tolerated(self):
        orders = [
            {
                "source_name": "chatgpt",
                "total_price": "not a number",
                "created_at_ts": 1_000_000.0,
            },
        ]
        out = self.b.aggregate(orders)
        self.assertEqual(out[0].gmv_usd, 0.0)


class TestSingleton(unittest.TestCase):
    def test_singleton(self):
        reset_agentic_bridge_for_tests()
        try:
            a = get_agentic_bridge()
            b = get_agentic_bridge()
            self.assertIs(a, b)
        finally:
            reset_agentic_bridge_for_tests()


class TestDicts(unittest.TestCase):
    def test_status_dict(self):
        s = ChannelStatus(
            channel="chatgpt", enabled=True,
        )
        self.assertIn("channel", s.as_dict())

    def test_metrics_dict(self):
        m = ChannelMetrics(
            channel="chatgpt", orders=2,
            gmv_usd=80.0, refunds_usd=0.0,
            aov_usd=40.0, window_days=7,
        )
        self.assertEqual(m.as_dict()["aov_usd"], 40.0)


if __name__ == "__main__":
    unittest.main()
