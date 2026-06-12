"""W963-151: Klaviyo webhook vendor handler tests."""
from __future__ import annotations

import base64
import hashlib
import hmac
from unittest.mock import patch

import pytest

from core.webhooks.external import (
    EVENT_ENGINE_MAP,
    ExternalWebhookHandler,
    KlaviyoVendorHandler,
)
from core.webhooks.external.vendors.klaviyo import (
    _normalise_topic,
)


class TestNormaliseTopic:
    def test_aliases(self):
        assert _normalise_topic(
            "Unsubscribed",
        ) == "unsubscribe"
        assert _normalise_topic(
            "Bounced Email",
        ) == "bounce"
        assert _normalise_topic(
            "Marked Email as Spam",
        ) == "spam_report"
        assert _normalise_topic(
            "Placed Order",
        ) == "metric.placed_order"

    def test_passthrough(self):
        assert _normalise_topic(
            "open",
        ) == "open"
        assert _normalise_topic(
            "click",
        ) == "click"


class TestHMAC:
    def test_no_secret_skips(self, monkeypatch):
        monkeypatch.delenv(
            "KLAVIYO_WEBHOOK_SECRET", raising=False,
        )
        v = KlaviyoVendorHandler()
        assert v.verify_hmac(b"body", "anything") is True

    def test_valid_signature(self, monkeypatch):
        monkeypatch.setenv(
            "KLAVIYO_WEBHOOK_SECRET", "secret",
        )
        v = KlaviyoVendorHandler()
        body = b'{"type":"event"}'
        sig = base64.b64encode(
            hmac.new(
                b"secret", body, hashlib.sha256,
            ).digest(),
        ).decode("ascii")
        assert v.verify_hmac(body, sig) is True

    def test_invalid_signature(self, monkeypatch):
        monkeypatch.setenv(
            "KLAVIYO_WEBHOOK_SECRET", "secret",
        )
        v = KlaviyoVendorHandler()
        assert v.verify_hmac(
            b"body", "wrong_sig",
        ) is False


class TestTopicExtraction:
    def test_2024_api_shape(self):
        v = KlaviyoVendorHandler()
        topic = v.extract_topic({
            "type": "event",
            "attributes": {
                "metric": {"name": "Unsubscribed"},
            },
        }, {})
        assert topic == "unsubscribe"

    def test_legacy_shape(self):
        v = KlaviyoVendorHandler()
        topic = v.extract_topic({
            "event_name": "unsubscribe",
        }, {})
        assert topic == "unsubscribe"

    def test_unknown_fallback(self):
        v = KlaviyoVendorHandler()
        topic = v.extract_topic({}, {})
        assert topic == "unknown"


class TestStoreIdentifier:
    def test_from_profile_properties(self):
        v = KlaviyoVendorHandler()
        sid = v.extract_store_identifier({
            "attributes": {
                "profile": {
                    "properties": {
                        "shop_url": (
                            "store-a.myshopify.com"
                        ),
                    },
                },
            },
        }, {})
        assert sid == "store-a.myshopify.com"

    def test_from_event_properties(self):
        v = KlaviyoVendorHandler()
        sid = v.extract_store_identifier({
            "attributes": {
                "event_properties": {
                    "shopai_store_id": "store_a",
                },
            },
        }, {})
        assert sid == "store_a"

    def test_legacy_person_shape(self):
        v = KlaviyoVendorHandler()
        sid = v.extract_store_identifier({
            "person": {
                "shop_url": "x.myshopify.com",
            },
        }, {})
        assert sid == "x.myshopify.com"

    def test_no_data_returns_empty(self):
        v = KlaviyoVendorHandler()
        assert v.extract_store_identifier(
            {}, {},
        ) == ""


class TestNormalisePayload:
    def test_flattens_2024_api_shape(self):
        v = KlaviyoVendorHandler()
        out = v.normalise_payload(
            "unsubscribe",
            {
                "type": "event",
                "attributes": {
                    "metric": {
                        "name": "Unsubscribed",
                    },
                    "profile": {
                        "email": "x@y.z",
                    },
                    "event_properties": {
                        "list_id": "L1",
                    },
                    "value": 0,
                    "datetime": "2026-06-12T00:00Z",
                },
            },
        )
        assert out["topic_raw"] == "Unsubscribed"
        assert out["profile"]["email"] == "x@y.z"
        assert out["event_properties"]["list_id"] == "L1"
        assert out["timestamp"] == "2026-06-12T00:00Z"


class TestMapping:
    def test_klaviyo_topics_mapped(self):
        for t in (
            "klaviyo.unsubscribe",
            "klaviyo.bounce",
            "klaviyo.spam_report",
            "klaviyo.open",
            "klaviyo.click",
            "klaviyo.metric.placed_order",
        ):
            assert t in EVENT_ENGINE_MAP

    def test_unsubscribe_routes(self):
        engines = [
            m["engine"] for m in
            EVENT_ENGINE_MAP["klaviyo.unsubscribe"]
        ]
        assert "customer_outreach" in engines
        assert "customer_segmentation" in engines

    def test_spam_report_routes_to_fraud(self):
        engines = [
            m["engine"] for m in
            EVENT_ENGINE_MAP["klaviyo.spam_report"]
        ]
        assert "fraud_detection" in engines


class TestEndToEnd:
    def test_unsubscribe_dispatches_two_engines(self):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(KlaviyoVendorHandler())
        triggered: list[str] = []

        def fake_trigger(name, data, eid):
            triggered.append(name)
            return {"engine": name, "status": "success"}

        with patch.object(
            ExternalWebhookHandler,
            "_trigger_engine",
            staticmethod(fake_trigger),
        ), patch(
            "data_pipeline.store.store_manager."
            "StoreManager",
        ):
            outcome = h.handle(
                "klaviyo",
                {
                    "type": "event",
                    "attributes": {
                        "metric": {
                            "name": "Unsubscribed",
                        },
                        "profile": {
                            "email": "x@y.z",
                            "properties": {
                                "shop_url": (
                                    "store-a"
                                    ".myshopify.com"
                                ),
                            },
                        },
                    },
                },
                event_id="evt_unsub_1",
            )
        assert outcome.status == "processed"
        assert "customer_outreach" in triggered
        assert "customer_segmentation" in triggered

    def test_placed_order_routes_to_revenue(self):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(KlaviyoVendorHandler())
        triggered: list[str] = []
        with patch.object(
            ExternalWebhookHandler,
            "_trigger_engine",
            staticmethod(
                lambda n, d, e: (
                    triggered.append(n) or {
                        "engine": n,
                        "status": "success",
                    }
                ),
            ),
        ), patch(
            "data_pipeline.store.store_manager."
            "StoreManager",
        ):
            outcome = h.handle(
                "klaviyo",
                {
                    "type": "event",
                    "attributes": {
                        "metric": {
                            "name": "Placed Order",
                        },
                        "value": 49.99,
                    },
                },
                event_id="evt_ord_1",
            )
        assert outcome.status == "processed"
        assert "revenue_attribution" in triggered
