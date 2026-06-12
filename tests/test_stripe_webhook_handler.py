"""W963-150: Stripe webhook vendor handler tests."""
from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import patch

import pytest

from core.webhooks.external import (
    EVENT_ENGINE_MAP,
    ExternalWebhookHandler,
    StripeVendorHandler,
)
from core.webhooks.external.vendors.stripe import (
    _STRIPE_TOLERANCE_SECONDS,
    _parse_signature_header,
)


class TestSignatureParse:
    def test_parses_v1_signature(self):
        ts, sigs = _parse_signature_header(
            "t=1700000000,v1=abc,v0=def",
        )
        assert ts == 1700000000
        assert "abc" in sigs
        assert "def" in sigs

    def test_empty_header(self):
        ts, sigs = _parse_signature_header("")
        assert ts == 0
        assert sigs == []

    def test_malformed(self):
        ts, sigs = _parse_signature_header(
            "garbage_no_equals_here",
        )
        assert ts == 0
        assert sigs == []


class TestHMAC:
    def _signed_request(
        self, body: bytes, secret: str,
        timestamp: int | None = None,
    ) -> str:
        ts = timestamp or int(time.time())
        signed_payload = (
            f"{ts}.".encode("utf-8") + body
        )
        sig = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
        return f"t={ts},v1={sig}"

    def test_no_secret_skips_verification(
        self, monkeypatch,
    ):
        monkeypatch.delenv(
            "STRIPE_WEBHOOK_SECRET", raising=False,
        )
        v = StripeVendorHandler()
        assert v.verify_hmac(b"body", "anything") is True

    def test_valid_signature_passes(self, monkeypatch):
        monkeypatch.setenv(
            "STRIPE_WEBHOOK_SECRET", "secret123",
        )
        v = StripeVendorHandler()
        body = b'{"id":"evt_x","type":"charge.refunded"}'
        sig = self._signed_request(body, "secret123")
        assert v.verify_hmac(body, sig) is True

    def test_invalid_signature_rejected(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "STRIPE_WEBHOOK_SECRET", "secret123",
        )
        v = StripeVendorHandler()
        body = b'{"id":"evt_x"}'
        # Sign with WRONG secret
        sig = self._signed_request(body, "wrong_secret")
        assert v.verify_hmac(body, sig) is False

    def test_stale_timestamp_rejected(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "STRIPE_WEBHOOK_SECRET", "secret123",
        )
        v = StripeVendorHandler()
        body = b'{"id":"evt_x"}'
        # 10 minutes ago -- beyond 5-min tolerance
        old_ts = int(time.time()) - 600
        sig = self._signed_request(
            body, "secret123", timestamp=old_ts,
        )
        assert v.verify_hmac(body, sig) is False

    def test_replay_protection_window(self):
        assert _STRIPE_TOLERANCE_SECONDS == 300


class TestTopicExtraction:
    def test_top_level_type(self):
        v = StripeVendorHandler()
        topic = v.extract_topic(
            {"type": "charge.dispute.created"}, {},
        )
        assert topic == "charge.dispute.created"

    def test_missing_type(self):
        v = StripeVendorHandler()
        topic = v.extract_topic({}, {})
        assert topic == "unknown"


class TestStoreIdentifier:
    def test_shop_url_from_metadata(self):
        v = StripeVendorHandler()
        sid = v.extract_store_identifier({
            "data": {
                "object": {
                    "metadata": {
                        "shop_url": (
                            "store-a.myshopify.com"
                        ),
                    },
                },
            },
        }, {})
        assert sid == "store-a.myshopify.com"

    def test_shopai_store_id_from_metadata(self):
        v = StripeVendorHandler()
        sid = v.extract_store_identifier({
            "data": {
                "object": {
                    "metadata": {
                        "shopai_store_id": "store_a",
                    },
                },
            },
        }, {})
        assert sid == "store_a"

    def test_no_metadata_returns_empty(self):
        v = StripeVendorHandler()
        sid = v.extract_store_identifier({
            "data": {"object": {}},
        }, {})
        assert sid == ""


class TestNormalisePayload:
    def test_data_object_unwrapped(self):
        v = StripeVendorHandler()
        out = v.normalise_payload(
            "charge.refunded",
            {
                "id": "evt_123",
                "type": "charge.refunded",
                "data": {
                    "object": {
                        "id": "ch_456",
                        "amount": 5000,
                    },
                },
            },
        )
        assert out["id"] == "ch_456"
        assert out["amount"] == 5000
        # Carry-over for downstream idempotency
        assert out["_stripe_event_id"] == "evt_123"
        assert out["_stripe_event_type"] == (
            "charge.refunded"
        )


class TestMapping:
    def test_stripe_topics_mapped(self):
        assert (
            "stripe.charge.dispute.created"
            in EVENT_ENGINE_MAP
        )
        assert (
            "stripe.charge.dispute.closed"
            in EVENT_ENGINE_MAP
        )
        assert (
            "stripe.charge.refunded"
            in EVENT_ENGINE_MAP
        )
        assert (
            "stripe.payout.created"
            in EVENT_ENGINE_MAP
        )

    def test_dispute_routes_to_fraud_and_refund(self):
        engines = [
            m["engine"] for m in
            EVENT_ENGINE_MAP[
                "stripe.charge.dispute.created"
            ]
        ]
        assert "fraud_detection" in engines
        assert "refund_processing" in engines


class TestEndToEnd:
    def test_dispute_routes_with_prefix(self):
        """W963-150 fix: dotted topics still prefix
        with vendor name."""
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(StripeVendorHandler())

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
                "stripe",
                {
                    "id": "evt_dispute_1",
                    "type": "charge.dispute.created",
                    "data": {
                        "object": {
                            "id": "dp_xyz",
                            "amount": 4500,
                            "metadata": {
                                "shop_url": (
                                    "store-a"
                                    ".myshopify.com"
                                ),
                            },
                        },
                    },
                },
                event_id="evt_dispute_1",
            )
        assert outcome.status == "processed"
        # Both engines should fire per the map
        assert "fraud_detection" in triggered
        assert "refund_processing" in triggered

    def test_unknown_stripe_topic_skipped(self):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(StripeVendorHandler())
        outcome = h.handle(
            "stripe",
            {
                "id": "evt_unknown",
                "type": "some.unmapped.event",
                "data": {"object": {}},
            },
            event_id="evt_unknown",
        )
        assert outcome.status == "skipped"
        assert "no_mapping" in outcome.reason
