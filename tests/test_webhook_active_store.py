"""W963-128: webhook handler maps shop URL back to
store_id + wraps engine.run in active_store(sid).

Pre-fix every webhook-triggered engine resolved env-
default credentials. A fulfillment webhook for store_b
would hit Shopify with store_a's token if store_a was
the env default -- per-store substrate dormant on the
webhook path same as it was on the cycle path before
W963-127.

W963-128 closes the webhook side:
  1. New StoreManager.find_by_shop_url(shop) reverse
     lookup
  2. _trigger_engine called inside
     active_store(webhook_sid) so adapters resolve the
     right credentials + cost events tag correctly
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── StoreManager.find_by_shop_url ─────────────────────────


class TestFindByShopUrl:
    def test_returns_empty_for_empty(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        assert sm.find_by_shop_url("") == ""
        assert sm.find_by_shop_url(None) == ""

    def test_returns_empty_for_unknown(self):
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        assert sm.find_by_shop_url(
            "not-a-real-shop.myshopify.com",
        ) == ""

    def test_normalises_https_prefix(self, monkeypatch):
        """Shopify webhooks deliver shop URLs as
        'store.myshopify.com'; some clients send
        'https://store.myshopify.com/'. Both must match
        the stored 'store.myshopify.com' canonical form.
        """
        from data_pipeline.store.store_manager import (
            StoreManager,
        )
        sm = StoreManager()
        with sm._lock:
            sm._store_credentials["store_a"] = {
                "shop_url": "store-a.myshopify.com",
                "api_key": "key_a",
                "client_id": "",
                "client_secret": "",
            }
        try:
            # Exact match
            assert sm.find_by_shop_url(
                "store-a.myshopify.com",
            ) == "store_a"
            # https://
            assert sm.find_by_shop_url(
                "https://store-a.myshopify.com",
            ) == "store_a"
            # trailing /
            assert sm.find_by_shop_url(
                "store-a.myshopify.com/",
            ) == "store_a"
            # https://...//
            assert sm.find_by_shop_url(
                "https://store-a.myshopify.com/",
            ) == "store_a"
            # case-insensitive
            assert sm.find_by_shop_url(
                "STORE-A.MYSHOPIFY.COM",
            ) == "store_a"
        finally:
            with sm._lock:
                sm._store_credentials.pop("store_a", None)


# ── Webhook handler wraps engine.run ──────────────────────


class TestWebhookActiveStoreWrap:
    def test_engine_invoked_inside_active_store(
        self, monkeypatch,
    ):
        """When the webhook's shop URL maps to a known
        store_id, _trigger_engine is called inside
        active_store(sid)."""
        from core.webhooks import ShopifyWebhookHandler
        from core.context import get_active_store_id

        captured: dict = {"sid": None}

        def fake_trigger(self, engine_name, data, priority, event_id):
            # Inside the trigger call -- check sid
            captured["sid"] = get_active_store_id() or ""
            return {
                "engine": engine_name,
                "status": "completed",
            }

        # Stub StoreManager
        fake_sm = MagicMock()
        fake_sm.find_by_shop_url.return_value = "store_a"

        processor = ShopifyWebhookHandler()
        # Register a mapping so the webhook routes to an
        # engine
        from core.webhooks import EVENT_ENGINE_MAP
        EVENT_ENGINE_MAP.setdefault(
            "test/topic_w963_128",
            [{
                "engine": "test_engine",
                "data_key": "data",
                "priority": "low",
            }],
        )
        try:
            with patch(
                "data_pipeline.store.store_manager.StoreManager",
                return_value=fake_sm,
            ), patch.object(
                ShopifyWebhookHandler, "_trigger_engine",
                fake_trigger,
            ):
                processor.handle(
                    topic="test/topic_w963_128",
                    payload={},
                    shop="store-a.myshopify.com",
                )
        finally:
            EVENT_ENGINE_MAP.pop(
                "test/topic_w963_128", None,
            )

        # Inside the engine: active_store was set to
        # store_a
        assert captured["sid"] == "store_a"

    def test_no_shop_match_falls_through(
        self, monkeypatch,
    ):
        """When shop URL does NOT match any store, the
        webhook still fires the engine but without an
        active_store wrap. Backward-compatible."""
        from core.webhooks import ShopifyWebhookHandler
        from core.context import get_active_store_id

        captured: dict = {"sid": "(unset)"}

        def fake_trigger(self, engine_name, data, priority, event_id):
            captured["sid"] = (
                get_active_store_id() or ""
            )
            return {
                "engine": engine_name,
                "status": "completed",
            }

        fake_sm = MagicMock()
        fake_sm.find_by_shop_url.return_value = ""

        processor = ShopifyWebhookHandler()
        from core.webhooks import EVENT_ENGINE_MAP
        EVENT_ENGINE_MAP.setdefault(
            "test/topic_w963_128_no_match",
            [{
                "engine": "test_engine",
                "data_key": "data",
                "priority": "low",
            }],
        )
        try:
            with patch(
                "data_pipeline.store.store_manager.StoreManager",
                return_value=fake_sm,
            ), patch.object(
                ShopifyWebhookHandler, "_trigger_engine",
                fake_trigger,
            ):
                processor.handle(
                    topic="test/topic_w963_128_no_match",
                    payload={},
                    shop="unknown.myshopify.com",
                )
        finally:
            EVENT_ENGINE_MAP.pop(
                "test/topic_w963_128_no_match", None,
            )

        # No wrap -- active store reflects whatever was
        # set before this test (could be empty or '(unset)')
        assert captured["sid"] in (
            "", "(unset)", "main",
        ) or captured["sid"] is None

    def test_no_shop_param_falls_through(
        self, monkeypatch,
    ):
        """No shop URL passed at all -> no wrap (back-
        compat)."""
        from core.webhooks import ShopifyWebhookHandler
        from core.context import get_active_store_id

        captured: dict = {"sid": "(unset)"}

        def fake_trigger(self, engine_name, data, priority, event_id):
            captured["sid"] = (
                get_active_store_id() or ""
            )
            return {
                "engine": engine_name,
                "status": "completed",
            }

        processor = ShopifyWebhookHandler()
        from core.webhooks import EVENT_ENGINE_MAP
        EVENT_ENGINE_MAP.setdefault(
            "test/topic_w963_128_no_shop",
            [{
                "engine": "test_engine",
                "data_key": "data",
                "priority": "low",
            }],
        )
        try:
            with patch.object(
                ShopifyWebhookHandler, "_trigger_engine",
                fake_trigger,
            ):
                processor.handle(
                    topic="test/topic_w963_128_no_shop",
                    payload={},
                    shop="",  # no shop URL
                )
        finally:
            EVENT_ENGINE_MAP.pop(
                "test/topic_w963_128_no_shop", None,
            )

        # No wrap fired
        assert captured["sid"] in (
            "", "(unset)", "main",
        ) or captured["sid"] is None
