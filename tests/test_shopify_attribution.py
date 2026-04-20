"""Shopify attribution tests."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from execution.launch import shopify_attribution as sa


class TestSnippet(unittest.TestCase):
    def test_snippet_includes_decision_key(self):
        s = sa.build_liquid_snippet()
        self.assertIn('"shopai_decision_id"', s)
        self.assertIn('"utm_source"', s)
        self.assertIn('"utm_campaign"', s)

    def test_snippet_has_js_fetch_call(self):
        s = sa.build_liquid_snippet()
        self.assertIn("/cart/update.js", s)

    def test_snippet_is_idempotent_storage(self):
        s = sa.build_liquid_snippet()
        self.assertIn("sessionStorage", s)

    def test_extra_keys_included(self):
        s = sa.build_liquid_snippet(
            extra_keys=("fbclid", "gclid"),
        )
        self.assertIn('"fbclid"', s)
        self.assertIn('"gclid"', s)

    def test_install_instructions_mention_theme_liquid(self):
        doc = sa.install_instructions("example.myshopify.com")
        self.assertIn("theme.liquid", doc)
        self.assertIn("example.myshopify.com", doc)


class TestListWebhooks(unittest.TestCase):
    def test_blank_url_raises(self):
        with self.assertRaises(ValueError):
            sa.list_registered_webhooks("", "tok")

    def test_returns_empty_on_http_error(self):
        client = MagicMock()
        client.get.return_value.status_code = 500
        client.get.return_value.text = "oops"
        result = sa.list_registered_webhooks(
            "s.myshopify.com", "tok", http=client,
        )
        self.assertEqual(result, [])

    def test_parses_success(self):
        client = MagicMock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [
                {
                    "id": 42,
                    "topic": "orders/paid",
                    "address": "https://x.example/wh",
                },
            ],
        }
        result = sa.list_registered_webhooks(
            "s.myshopify.com", "tok", http=client,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 42)


class TestRegister(unittest.TestCase):
    def test_requires_full_callback_url(self):
        with self.assertRaises(ValueError):
            sa.register_order_webhook(
                "s.myshopify.com", "tok",
                callback_url="not-a-url",
            )

    def test_blank_args_raise(self):
        with self.assertRaises(ValueError):
            sa.register_order_webhook(
                "", "tok",
                callback_url="https://x.example/wh",
            )
        with self.assertRaises(ValueError):
            sa.register_order_webhook(
                "s.myshopify.com", "",
                callback_url="https://x.example/wh",
            )
        with self.assertRaises(ValueError):
            sa.register_order_webhook(
                "s.myshopify.com", "tok", callback_url="",
            )

    def test_creates_when_missing(self):
        client = MagicMock()
        # list returns empty
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [],
        }
        # post creates
        client.post.return_value.status_code = 201
        client.post.return_value.json.return_value = {
            "webhook": {
                "id": 99,
                "topic": "orders/paid",
                "address": "https://x.example/wh",
            },
        }
        state = sa.register_order_webhook(
            "s.myshopify.com", "tok",
            "https://x.example/wh", http=client,
        )
        self.assertTrue(state.registered)
        self.assertFalse(state.already_existed)
        self.assertEqual(state.id, "99")
        client.post.assert_called_once()

    def test_idempotent_when_existing(self):
        client = MagicMock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [
                {
                    "id": 42,
                    "topic": "orders/paid",
                    "address": "https://x.example/wh",
                },
            ],
        }
        state = sa.register_order_webhook(
            "s.myshopify.com", "tok",
            "https://x.example/wh", http=client,
        )
        self.assertTrue(state.registered)
        self.assertTrue(state.already_existed)
        self.assertEqual(state.id, "42")
        # Didn't call POST
        client.post.assert_not_called()

    def test_surfaces_http_error(self):
        client = MagicMock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [],
        }
        client.post.return_value.status_code = 401
        client.post.return_value.text = "unauthorized"
        state = sa.register_order_webhook(
            "s.myshopify.com", "tok",
            "https://x.example/wh", http=client,
        )
        self.assertFalse(state.registered)
        self.assertIn("401", state.error)

    def test_surfaces_exception(self):
        client = MagicMock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [],
        }
        client.post.side_effect = RuntimeError("network down")
        state = sa.register_order_webhook(
            "s.myshopify.com", "tok",
            "https://x.example/wh", http=client,
        )
        self.assertFalse(state.registered)
        self.assertIn("RuntimeError", state.error)


class TestEnsure(unittest.TestCase):
    def test_registers_both_topics(self):
        client = MagicMock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [],
        }
        client.post.return_value.status_code = 201
        client.post.return_value.json.return_value = {
            "webhook": {
                "id": 42,
                "topic": "orders/paid",
                "address": "https://x.example/wh",
            },
        }
        states = sa.ensure_attribution(
            shop_url="s.myshopify.com",
            api_key="tok",
            callback_url="https://x.example/wh",
            http=client,
        )
        self.assertEqual(len(states), 2)
        topics = {s.topic for s in states}
        self.assertEqual(
            topics, {"orders/paid", "orders/cancelled"},
        )


class TestStats(unittest.TestCase):
    def test_stats_tracks_usage(self):
        before = dict(sa.stats())
        sa.build_liquid_snippet()
        after = sa.stats()
        self.assertEqual(
            after["snippets_built"] - before["snippets_built"],
            1,
        )

    def test_webhook_creation_counted(self):
        client = MagicMock()
        client.get.return_value.status_code = 200
        client.get.return_value.json.return_value = {
            "webhooks": [],
        }
        client.post.return_value.status_code = 201
        client.post.return_value.json.return_value = {
            "webhook": {
                "id": 7,
                "topic": "orders/paid",
                "address": "https://x.example/wh",
            },
        }
        before = sa.stats().get("webhooks_created", 0)
        sa.register_order_webhook(
            "s.myshopify.com", "tok",
            "https://x.example/wh", http=client,
        )
        self.assertEqual(
            sa.stats()["webhooks_created"] - before, 1,
        )


class TestDict(unittest.TestCase):
    def test_state_serialises(self):
        s = sa.WebhookState(
            topic="orders/paid",
            address="https://x/wh",
            id="1", registered=True,
        )
        d = s.as_dict()
        self.assertEqual(d["topic"], "orders/paid")


if __name__ == "__main__":
    unittest.main()
