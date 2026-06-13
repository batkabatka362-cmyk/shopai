"""W963-154: PayPal webhook vendor handler tests."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.webhooks.external import (
    EVENT_ENGINE_MAP,
    ExternalWebhookHandler,
    PayPalVendorHandler,
)


class TestHMAC:
    def test_no_webhook_id_accepts_all(
        self, monkeypatch,
    ):
        monkeypatch.delenv(
            "PAYPAL_WEBHOOK_ID", raising=False,
        )
        v = PayPalVendorHandler()
        assert v.verify_hmac(b"any", "any") is True

    def test_matching_webhook_id(self, monkeypatch):
        monkeypatch.setenv(
            "PAYPAL_WEBHOOK_ID", "WHK-123",
        )
        v = PayPalVendorHandler()
        assert v.verify_hmac(
            b"body", "WHK-123-sub",
        ) is True

    def test_wrong_webhook_id_rejected(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "PAYPAL_WEBHOOK_ID", "WHK-123",
        )
        v = PayPalVendorHandler()
        assert v.verify_hmac(
            b"body", "WHK-OTHER",
        ) is False

    def test_empty_signature_rejected(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "PAYPAL_WEBHOOK_ID", "WHK-123",
        )
        v = PayPalVendorHandler()
        assert v.verify_hmac(b"body", "") is False


class TestTopicExtraction:
    def test_event_type_lowercased(self):
        v = PayPalVendorHandler()
        assert v.extract_topic(
            {
                "event_type":
                    "PAYMENT.CAPTURE.COMPLETED",
            }, {},
        ) == "payment.capture.completed"

    def test_missing_event_type(self):
        v = PayPalVendorHandler()
        assert v.extract_topic({}, {}) == "unknown"


class TestStoreIdentifier:
    def test_custom_id_preferred(self, monkeypatch):
        monkeypatch.setenv(
            "PAYPAL_DEFAULT_STORE", "fallback_store",
        )
        v = PayPalVendorHandler()
        sid = v.extract_store_identifier(
            {
                "resource": {
                    "custom_id": "shopai_store_42",
                    "invoice_number": "ord_99",
                },
            }, {},
        )
        assert sid == "shopai_store_42"

    def test_invoice_number_fallback(self):
        v = PayPalVendorHandler()
        sid = v.extract_store_identifier(
            {
                "resource": {
                    "invoice_number": "ord_99",
                },
            }, {},
        )
        assert sid == "ord_99"

    def test_dispute_resource_nesting(self):
        v = PayPalVendorHandler()
        sid = v.extract_store_identifier(
            {
                "resource": {
                    "disputed_transactions": [{
                        "invoice_number": "ord_dispute",
                    }],
                },
            }, {},
        )
        assert sid == "ord_dispute"

    def test_no_resource_default_store(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "PAYPAL_DEFAULT_STORE", "store_default",
        )
        v = PayPalVendorHandler()
        sid = v.extract_store_identifier({}, {})
        assert sid == "store_default"

    def test_no_default_no_resource_empty(
        self, monkeypatch,
    ):
        monkeypatch.delenv(
            "PAYPAL_DEFAULT_STORE", raising=False,
        )
        v = PayPalVendorHandler()
        assert v.extract_store_identifier({}, {}) == ""


class TestNormalisePayload:
    def test_flattens_capture_completed(self):
        v = PayPalVendorHandler()
        out = v.normalise_payload(
            "payment.capture.completed",
            {
                "id": "WH-1",
                "event_type": "PAYMENT.CAPTURE.COMPLETED",
                "create_time":
                    "2026-06-13T00:00:00Z",
                "resource": {
                    "id": "CAP-100",
                    "status": "COMPLETED",
                    "amount": {
                        "value": "49.99",
                        "currency_code": "USD",
                    },
                    "invoice_number": "ord_99",
                    "custom_id": "shopai_store_42",
                },
            },
        )
        assert out["paypal_id"] == "CAP-100"
        assert out["amount"] == 49.99
        assert out["currency"] == "USD"
        assert out["status"] == "COMPLETED"
        assert out["invoice_number"] == "ord_99"
        assert out["custom_id"] == "shopai_store_42"
        assert out["_paypal_event_id"] == "WH-1"

    def test_amount_invalid_defaults_zero(self):
        v = PayPalVendorHandler()
        out = v.normalise_payload(
            "payment.capture.completed",
            {
                "resource": {
                    "amount": {
                        "value": "not a number",
                    },
                },
            },
        )
        assert out["amount"] == 0.0

    def test_dispute_reason_surfaced(self):
        v = PayPalVendorHandler()
        out = v.normalise_payload(
            "customer.dispute.created",
            {
                "resource": {
                    "id": "DISP-1",
                    "reason": "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED",
                    "dispute_outcome": {
                        "outcome_code":
                            "RESOLVED_BUYER_FAVOUR",
                    },
                },
            },
        )
        assert out["dispute_reason"].startswith(
            "MERCHANDISE",
        )
        assert "RESOLVED" in out["dispute_outcome"]

    def test_no_resource_returns_raw(self):
        v = PayPalVendorHandler()
        out = v.normalise_payload(
            "payment.capture.completed",
            {"event_type": "X"},
        )
        assert "event_type" in out


class TestMapping:
    def test_paypal_topics_mapped(self):
        for t in (
            "paypal.payment.capture.completed",
            "paypal.payment.capture.refunded",
            "paypal.payment.capture.reversed",
            "paypal.customer.dispute.created",
            "paypal.customer.dispute.resolved",
            "paypal.billing.subscription.cancelled",
        ):
            assert t in EVENT_ENGINE_MAP

    def test_dispute_created_routes_dual(self):
        engines = [
            m["engine"] for m in EVENT_ENGINE_MAP[
                "paypal.customer.dispute.created"
            ]
        ]
        assert "customer_support" in engines
        assert "fraud_detection" in engines


class TestEndToEnd:
    def test_capture_completed_dispatches(self):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(PayPalVendorHandler())
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
                "paypal",
                {
                    "id": "WH-99",
                    "event_type":
                        "PAYMENT.CAPTURE.COMPLETED",
                    "resource": {
                        "id": "CAP-200",
                        "amount": {
                            "value": "100.00",
                            "currency_code": "USD",
                        },
                        "custom_id":
                            "store-a.myshopify.com",
                    },
                },
                event_id="evt_cap_1",
            )
        assert outcome.status == "processed"
        assert "revenue_attribution" in triggered
        ev = captured.get("paypal_event") or {}
        assert ev.get("amount") == 100.0

    def test_dispute_created_routes_both_engines(self):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(PayPalVendorHandler())
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
                "paypal",
                {
                    "id": "WH-100",
                    "event_type":
                        "CUSTOMER.DISPUTE.CREATED",
                    "resource": {
                        "id": "DISP-1",
                        "custom_id":
                            "store-a.myshopify.com",
                        "reason": "FRAUD",
                    },
                },
                event_id="evt_disp_1",
            )
        assert outcome.status == "processed"
        assert "customer_support" in triggered
        assert "fraud_detection" in triggered
