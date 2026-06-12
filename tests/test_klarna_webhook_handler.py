"""W963-155: Klarna webhook vendor handler tests."""
from __future__ import annotations

import base64
import hashlib
import hmac
from unittest.mock import patch

import pytest

from core.webhooks.external import (
    EVENT_ENGINE_MAP,
    ExternalWebhookHandler,
    KlarnaVendorHandler,
)


class TestHMAC:
    def test_no_secret_accepts_all(self, monkeypatch):
        monkeypatch.delenv(
            "KLARNA_WEBHOOK_SECRET", raising=False,
        )
        v = KlarnaVendorHandler()
        assert v.verify_hmac(b"body", "any") is True

    def test_valid_signature(self, monkeypatch):
        monkeypatch.setenv(
            "KLARNA_WEBHOOK_SECRET", "klr_secret",
        )
        v = KlarnaVendorHandler()
        body = b'{"event_type":"order.captured"}'
        sig = base64.b64encode(
            hmac.new(
                b"klr_secret", body, hashlib.sha256,
            ).digest(),
        ).decode("ascii")
        assert v.verify_hmac(body, sig) is True

    def test_invalid_signature(self, monkeypatch):
        monkeypatch.setenv(
            "KLARNA_WEBHOOK_SECRET", "klr_secret",
        )
        v = KlarnaVendorHandler()
        assert v.verify_hmac(b"body", "wrong") is False


class TestTopicExtraction:
    def test_event_type_lowercased(self):
        v = KlarnaVendorHandler()
        assert v.extract_topic(
            {"event_type": "ORDER.CAPTURED"}, {},
        ) == "order.captured"

    def test_missing(self):
        v = KlarnaVendorHandler()
        assert v.extract_topic({}, {}) == "unknown"


class TestStoreIdentifier:
    def test_top_level_merchant_reference(self):
        v = KlarnaVendorHandler()
        sid = v.extract_store_identifier(
            {"merchant_reference": "ord_99"}, {},
        )
        assert sid == "ord_99"

    def test_nested_order_merchant_reference(self):
        v = KlarnaVendorHandler()
        sid = v.extract_store_identifier(
            {
                "data": {
                    "order": {
                        "merchant_reference":
                            "ord_nested",
                    },
                },
            }, {},
        )
        assert sid == "ord_nested"

    def test_shopai_store_id_fallback(self):
        v = KlarnaVendorHandler()
        sid = v.extract_store_identifier(
            {"shopai_store_id": "store_x"}, {},
        )
        assert sid == "store_x"

    def test_default_store_env(self, monkeypatch):
        monkeypatch.setenv(
            "KLARNA_DEFAULT_STORE", "fallback",
        )
        v = KlarnaVendorHandler()
        assert v.extract_store_identifier({}, {}) == (
            "fallback"
        )

    def test_no_field_no_env_empty(
        self, monkeypatch,
    ):
        monkeypatch.delenv(
            "KLARNA_DEFAULT_STORE", raising=False,
        )
        v = KlarnaVendorHandler()
        assert v.extract_store_identifier({}, {}) == ""


class TestNormalisePayload:
    def test_flattens_order_captured(self):
        v = KlarnaVendorHandler()
        out = v.normalise_payload(
            "order.captured",
            {
                "id": "evt_klr_1",
                "event_type": "order.captured",
                "merchant_reference": "ord_99",
                "data": {
                    "order": {
                        "order_id": "klarna_abc",
                        "order_amount": 4999,
                        "purchase_currency": "usd",
                        "status": "CAPTURED",
                    },
                },
            },
        )
        assert out["klarna_id"] == "klarna_abc"
        # 4999 cents -> 49.99
        assert out["amount"] == 49.99
        assert out["currency"] == "USD"
        assert out["status"] == "CAPTURED"
        assert out["merchant_reference"] == "ord_99"
        assert out["_klarna_event_id"] == "evt_klr_1"

    def test_invalid_amount_defaults_zero(self):
        v = KlarnaVendorHandler()
        out = v.normalise_payload(
            "order.captured",
            {
                "data": {
                    "order": {
                        "order_amount": "bad",
                    },
                },
            },
        )
        assert out["amount"] == 0.0

    def test_chargeback_reason_surfaced(self):
        v = KlarnaVendorHandler()
        out = v.normalise_payload(
            "order.chargeback",
            {
                "data": {
                    "order": {
                        "order_id": "klarna_cb",
                        "chargeback_reason": "FRAUD",
                    },
                },
            },
        )
        assert out["chargeback_reason"] == "FRAUD"

    def test_no_data_falls_back_to_top_level(self):
        v = KlarnaVendorHandler()
        out = v.normalise_payload(
            "order.captured",
            {
                "order_id": "top_level_id",
                "order_amount": 1000,
            },
        )
        assert out["klarna_id"] == "top_level_id"
        assert out["amount"] == 10.0


class TestMapping:
    def test_klarna_topics_mapped(self):
        for t in (
            "klarna.order.captured",
            "klarna.order.refunded",
            "klarna.order.cancelled",
            "klarna.order.chargeback",
            "klarna.subscription.cancelled",
        ):
            assert t in EVENT_ENGINE_MAP

    def test_chargeback_routes_dual(self):
        engines = [
            m["engine"] for m in EVENT_ENGINE_MAP[
                "klarna.order.chargeback"
            ]
        ]
        assert "customer_support" in engines
        assert "fraud_detection" in engines


class TestEndToEnd:
    def test_captured_dispatches_revenue_attribution(
        self,
    ):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(KlarnaVendorHandler())
        triggered: list[str] = []
        captured: dict = {}

        def fake_trigger(name, data, eid):
            triggered.append(name)
            captured.update(data)
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
                "klarna",
                {
                    "id": "evt_1",
                    "event_type": "order.captured",
                    "merchant_reference": "ord_99",
                    "data": {
                        "order": {
                            "order_id": "klarna_99",
                            "order_amount": 12345,
                            "purchase_currency": "USD",
                        },
                    },
                },
                event_id="evt_klarna_cap_1",
            )
        assert outcome.status == "processed"
        assert "revenue_attribution" in triggered
        ev = captured.get("klarna_event") or {}
        assert ev.get("amount") == 123.45

    def test_chargeback_routes_to_both_engines(self):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(KlarnaVendorHandler())
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
                "klarna",
                {
                    "id": "evt_2",
                    "event_type": "order.chargeback",
                    "merchant_reference": "ord_99",
                    "data": {
                        "order": {
                            "order_id": "klarna_99",
                            "chargeback_reason":
                                "UNAUTHORISED",
                        },
                    },
                },
                event_id="evt_klarna_cb_2",
            )
        assert outcome.status == "processed"
        assert "customer_support" in triggered
        assert "fraud_detection" in triggered
