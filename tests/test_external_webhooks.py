"""W963-147: unified external webhook ingestion tests."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from core.webhooks.external import (
    AfterShipVendorHandler,
    EVENT_ENGINE_MAP,
    ExternalWebhookHandler,
    GA4VendorHandler,
    GorgiasVendorHandler,
    VendorHandler,
)


class TestVendorRegistration:
    def test_register_vendor(self):
        h = ExternalWebhookHandler()
        v = GorgiasVendorHandler()
        h.register_vendor(v)
        assert "gorgias" in h._vendors

    def test_handle_unknown_vendor(self):
        h = ExternalWebhookHandler()
        outcome = h.handle(
            "totally_unknown", {"x": 1},
        )
        assert outcome.status == "rejected"
        assert "no_handler" in outcome.reason


class TestGorgiasHandler:
    def test_extract_topic_from_header(self):
        v = GorgiasVendorHandler()
        t = v.extract_topic(
            {}, {"X-Gorgias-Topic": "ticket_created"},
        )
        assert t == "ticket_created"

    def test_extract_topic_from_payload(self):
        v = GorgiasVendorHandler()
        t = v.extract_topic(
            {"event": "message_created"}, {},
        )
        assert t == "message_created"

    def test_hmac_skipped_when_no_secret(
        self, monkeypatch,
    ):
        monkeypatch.delenv(
            "GORGIAS_WEBHOOK_SECRET", raising=False,
        )
        v = GorgiasVendorHandler()
        assert v.verify_hmac(b"body", "x") is True

    def test_hmac_verifies_correct_signature(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "GORGIAS_WEBHOOK_SECRET", "secret123",
        )
        v = GorgiasVendorHandler()
        body = b'{"event":"ticket_created"}'
        sig = hmac.new(
            b"secret123", body, hashlib.sha256,
        ).hexdigest()
        assert v.verify_hmac(body, sig) is True
        assert v.verify_hmac(body, "wrong") is False


class TestAfterShipHandler:
    def test_extract_topic_from_msg(self):
        v = AfterShipVendorHandler()
        t = v.extract_topic({
            "msg": {
                "event": "tracking_status_updated",
            },
        }, {})
        assert t == "tracking_status_updated"

    def test_hmac_base64_match(self, monkeypatch):
        monkeypatch.setenv(
            "AFTERSHIP_WEBHOOK_SECRET", "secret",
        )
        v = AfterShipVendorHandler()
        body = b'{"msg":{"event":"x"}}'
        sig = base64.b64encode(
            hmac.new(
                b"secret", body, hashlib.sha256,
            ).digest(),
        ).decode("ascii")
        assert v.verify_hmac(body, sig) is True
        assert v.verify_hmac(body, "bad") is False

    def test_extract_store_from_title(self):
        v = AfterShipVendorHandler()
        sid = v.extract_store_identifier({
            "msg": {
                "title": "store-a.myshopify.com",
            },
        }, {})
        assert sid == "store-a.myshopify.com"


class TestGA4Handler:
    def test_extract_topic(self):
        v = GA4VendorHandler()
        t = v.extract_topic(
            {"event_name": "purchase"}, {},
        )
        assert t == "purchase"

    def test_store_from_custom_param(self):
        v = GA4VendorHandler()
        sid = v.extract_store_identifier(
            {"shopai_store_id": "store_a"}, {},
        )
        assert sid == "store_a"


class TestHandleEndToEnd:
    def _make_handler(self):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(GorgiasVendorHandler())
        h.register_vendor(AfterShipVendorHandler())
        h.register_vendor(GA4VendorHandler())
        return h

    def test_unmapped_topic_skipped(self):
        h = self._make_handler()
        outcome = h.handle(
            "gorgias",
            {"event": "unmapped_event"},
            event_id="evt_1",
        )
        assert outcome.status == "skipped"
        assert "no_mapping" in outcome.reason

    def test_duplicate_event_id_skipped(self):
        h = self._make_handler()
        # First call processes
        with patch(
            "core.webhooks.external.handler."
            "ExternalWebhookHandler._trigger_engine",
            return_value={
                "engine": "customer_support",
                "status": "success",
            },
        ), patch(
            "data_pipeline.store.store_manager."
            "StoreManager",
        ):
            outcome1 = h.handle(
                "gorgias",
                {"event": "ticket_created"},
                event_id="evt_dup_1",
            )
            outcome2 = h.handle(
                "gorgias",
                {"event": "ticket_created"},
                event_id="evt_dup_1",
            )
        assert outcome1.status == "processed"
        assert outcome2.status == "skipped"
        assert "duplicate" in outcome2.reason

    def test_mapped_topic_triggers_engines(self):
        h = self._make_handler()
        triggered: list[tuple[str, str]] = []

        def fake_trigger(name, data, eid):
            triggered.append((name, eid))
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
                "aftership",
                {
                    "msg": {
                        "event": (
                            "tracking_status_updated"
                        ),
                        "tracking_number": "1Z999",
                        "title": "store-a.myshopify.com",
                    },
                },
                event_id="evt_router_1",
            )
        assert outcome.status == "processed"
        # Both delivery_feedback + shipping_alert_autonomy
        # should be triggered for this topic
        engines_fired = [e for e, _ in triggered]
        assert (
            "delivery_feedback" in engines_fired
        )
        assert (
            "shipping_alert_autonomy" in engines_fired
        )

    def test_active_store_wrap_when_sid_resolves(
        self,
    ):
        """W963-141 Pattern CD: engine.run inside
        active_store(sid) when sid resolves."""
        h = self._make_handler()
        captured_sids: list[str] = []

        def fake_trigger(name, data, eid):
            from core.context import (
                get_active_store_id,
            )
            captured_sids.append(
                get_active_store_id() or "",
            )
            return {"engine": name, "status": "success"}

        fake_sm = MagicMock()
        fake_sm.find_by_shop_url.return_value = "store_a"
        fake_sm.has_store.return_value = True

        with patch.object(
            ExternalWebhookHandler,
            "_trigger_engine",
            staticmethod(fake_trigger),
        ), patch(
            "data_pipeline.store.store_manager."
            "StoreManager",
            return_value=fake_sm,
        ):
            h.handle(
                "aftership",
                {
                    "msg": {
                        "event": "tracking_delivered",
                        "title": "store-a.myshopify.com",
                    },
                },
                event_id="evt_wrap_1",
            )
        # Every engine fired inside active_store(store_a)
        assert all(
            sid == "store_a"
            for sid in captured_sids
        )

    def test_stats_tracked(self):
        h = self._make_handler()
        with patch.object(
            ExternalWebhookHandler,
            "_trigger_engine",
            staticmethod(
                lambda n, d, e: {
                    "engine": n, "status": "success",
                },
            ),
        ), patch(
            "data_pipeline.store.store_manager."
            "StoreManager",
        ):
            h.handle(
                "gorgias",
                {"event": "ticket_created"},
                event_id="s1",
            )
            h.handle(
                "gorgias",
                {"event": "unmapped"},
                event_id="s2",
            )
            h.handle(
                "totally_unknown_vendor",
                {},
                event_id="s3",
            )
        stats = h.get_stats()
        assert stats["received"] == 3
        assert stats["processed"] == 1
        assert stats["skipped"] == 1
        assert stats["rejected"] == 1


class TestEventEngineMap:
    def test_gorgias_topics_mapped(self):
        assert (
            "gorgias.ticket_created"
            in EVENT_ENGINE_MAP
        )
        assert (
            "gorgias.message_created"
            in EVENT_ENGINE_MAP
        )

    def test_aftership_topics_mapped(self):
        assert (
            "aftership.tracking_status_updated"
            in EVENT_ENGINE_MAP
        )
        assert (
            "aftership.tracking_delivered"
            in EVENT_ENGINE_MAP
        )
