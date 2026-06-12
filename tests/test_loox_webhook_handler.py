"""W963-152: Loox webhook vendor handler tests."""
from __future__ import annotations

import base64
import hashlib
import hmac
from unittest.mock import patch

import pytest

from core.webhooks.external import (
    EVENT_ENGINE_MAP,
    ExternalWebhookHandler,
    LooxVendorHandler,
)


class TestHMAC:
    def test_no_secret_skips(self, monkeypatch):
        monkeypatch.delenv(
            "LOOX_WEBHOOK_SECRET", raising=False,
        )
        v = LooxVendorHandler()
        assert v.verify_hmac(b"body", "x") is True

    def test_valid_signature(self, monkeypatch):
        monkeypatch.setenv(
            "LOOX_WEBHOOK_SECRET", "secret",
        )
        v = LooxVendorHandler()
        body = b'{"event":"review.created"}'
        sig = base64.b64encode(
            hmac.new(
                b"secret", body, hashlib.sha256,
            ).digest(),
        ).decode("ascii")
        assert v.verify_hmac(body, sig) is True

    def test_invalid_signature(self, monkeypatch):
        monkeypatch.setenv(
            "LOOX_WEBHOOK_SECRET", "secret",
        )
        v = LooxVendorHandler()
        assert v.verify_hmac(b"body", "bad") is False


class TestTopicExtraction:
    def test_event_field(self):
        v = LooxVendorHandler()
        assert v.extract_topic(
            {"event": "review.created"}, {},
        ) == "review.created"

    def test_missing(self):
        v = LooxVendorHandler()
        assert v.extract_topic({}, {}) == "unknown"


class TestStoreIdentifier:
    def test_shop_domain(self):
        v = LooxVendorHandler()
        sid = v.extract_store_identifier({
            "shop_domain": "store-a.myshopify.com",
        }, {})
        assert sid == "store-a.myshopify.com"

    def test_shopify_domain_alias(self):
        v = LooxVendorHandler()
        sid = v.extract_store_identifier({
            "shopify_domain": "store-b.myshopify.com",
        }, {})
        assert sid == "store-b.myshopify.com"

    def test_shopai_store_id_fallback(self):
        v = LooxVendorHandler()
        sid = v.extract_store_identifier({
            "shopai_store_id": "store_c",
        }, {})
        assert sid == "store_c"

    def test_no_field_returns_empty(self):
        v = LooxVendorHandler()
        assert v.extract_store_identifier(
            {}, {},
        ) == ""


class TestNormalisePayload:
    def test_flattens_review_with_media(self):
        v = LooxVendorHandler()
        out = v.normalise_payload(
            "review.created",
            {
                "event": "review.created",
                "shop_domain": "store-a.myshopify.com",
                "review": {
                    "id": 42,
                    "product_id": "prod_99",
                    "rating": 5,
                    "title": "Great!",
                    "body": "Loved it!",
                    "reviewer_name": "Jane Doe",
                    "reviewer_email": "j@d.com",
                    "photos": [
                        {"url": "https://x.png"},
                        {"url": "https://y.png"},
                    ],
                    "videos": [],
                    "is_published": True,
                    "created_at": "2026-06-12T00:00Z",
                },
            },
        )
        assert out["review_id"] == "42"
        assert out["product_id"] == "prod_99"
        assert out["rating"] == 5
        assert out["photo_count"] == 2
        assert out["video_count"] == 0
        assert out["has_media"] is True
        assert out["is_published"] is True
        assert out["_loox_event"] == "review.created"

    def test_no_media_no_flag(self):
        v = LooxVendorHandler()
        out = v.normalise_payload(
            "review.created",
            {
                "event": "review.created",
                "review": {
                    "id": 1,
                    "rating": 3,
                    "title": "ok",
                    "body": "",
                    "photos": [],
                    "videos": [],
                },
            },
        )
        assert out["has_media"] is False

    def test_rating_clamped(self):
        """Rating clamps to 0-5 if vendor sends weird
        value."""
        v = LooxVendorHandler()
        out = v.normalise_payload(
            "review.created",
            {
                "event": "review.created",
                "review": {"id": 1, "rating": 99},
            },
        )
        assert out["rating"] == 5

    def test_invalid_rating_defaults(self):
        v = LooxVendorHandler()
        out = v.normalise_payload(
            "review.created",
            {
                "event": "review.created",
                "review": {
                    "id": 1, "rating": "bad",
                },
            },
        )
        assert out["rating"] == 0

    def test_no_review_returns_raw(self):
        v = LooxVendorHandler()
        out = v.normalise_payload(
            "review.created",
            {"event": "review.created"},
        )
        # Falls through to raw payload
        assert "event" in out


class TestMapping:
    def test_loox_topics_mapped(self):
        for t in (
            "loox.review.created",
            "loox.review.published",
            "loox.review.declined",
            "loox.review.media_added",
        ):
            assert t in EVENT_ENGINE_MAP

    def test_review_created_routes(self):
        engines = [
            m["engine"] for m in
            EVENT_ENGINE_MAP["loox.review.created"]
        ]
        assert "reviews_management" in engines
        assert "customer_outreach" in engines


class TestEndToEnd:
    def test_review_created_dispatches_both_engines(
        self,
    ):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(LooxVendorHandler())
        triggered: list[str] = []
        captured_payload: dict = {}

        def fake_trigger(name, data, eid):
            triggered.append(name)
            captured_payload.update(data)
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
                "loox",
                {
                    "event": "review.created",
                    "shop_domain": (
                        "store-a.myshopify.com"
                    ),
                    "review": {
                        "id": 100,
                        "rating": 5,
                        "title": "Great",
                        "body": "Love",
                        "photos": [
                            {"url": "https://x.png"},
                        ],
                    },
                },
                event_id="evt_review_1",
            )
        assert outcome.status == "processed"
        assert "reviews_management" in triggered
        assert "customer_outreach" in triggered
        # Captured the flattened payload
        review = captured_payload.get("review") or {}
        assert review.get("review_id") == "100"
        assert review.get("has_media") is True

    def test_declined_routes_to_customer_support(self):
        h = ExternalWebhookHandler(
            verify_signatures=False,
        )
        h.register_vendor(LooxVendorHandler())
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
                "loox",
                {
                    "event": "review.declined",
                    "shop_domain": (
                        "store-a.myshopify.com"
                    ),
                    "review": {
                        "id": 200, "rating": 1,
                    },
                },
                event_id="evt_decl_1",
            )
        assert outcome.status == "processed"
        assert "customer_support" in triggered
