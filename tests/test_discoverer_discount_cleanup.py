"""Tests for discount_cleanup discoverer (Wave 830)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from core.automation.discoverers.discount_cleanup import (
    _classify_discount,
    _limit,
    _min_age_days,
    discover_discount_cleanup,
)
from core.automation.payload_discoverer import (
    discover, has_discoverer,
)


def _aged_iso(days: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).isoformat()


class TestRegistryWireup:

    def test_registered_after_import(self):
        assert has_discoverer("discount_cleanup")

    def test_dispatch_via_registry(self):
        with patch(
            "core.automation.discoverers.discount_cleanup."
            "_fetch_discounts",
            return_value=[],
        ):
            r = discover("discount_cleanup")
        assert r.ok
        assert r.source == "shopify_discounts"


class TestClassify:

    def test_unused_old_discount_surfaced(self):
        v = _classify_discount({
            "id": "d1",
            "code": "WELCOME",
            "status": "active",
            "created_at": _aged_iso(45),
            "usage_count": 0,
        }, min_age=30)
        assert v is not None
        reason, age_days = v
        assert "unused" in reason
        assert age_days >= 30

    def test_expired_discount_surfaced(self):
        v = _classify_discount({
            "id": "d1",
            "code": "SUMMER",
            "status": "active",
            "created_at": _aged_iso(100),
            "usage_count": 5,
            "ends_at": _aged_iso(10),
        }, min_age=30)
        assert v is not None
        assert "expired" in v[0]

    def test_too_young_skipped(self):
        assert _classify_discount({
            "id": "d1",
            "code": "X",
            "status": "active",
            "created_at": _aged_iso(15),
            "usage_count": 0,
        }, min_age=30) is None

    def test_already_inactive_skipped(self):
        assert _classify_discount({
            "id": "d1",
            "code": "X",
            "status": "deactivated",
            "created_at": _aged_iso(100),
        }, min_age=30) is None

    def test_active_used_unexpired_skipped(self):
        assert _classify_discount({
            "id": "d1",
            "code": "X",
            "status": "active",
            "created_at": _aged_iso(100),
            "usage_count": 50,
            "ends_at": _aged_iso(-30),  # future
        }, min_age=30) is None

    def test_no_created_at_skipped(self):
        assert _classify_discount({
            "id": "d1",
            "code": "X",
            "status": "active",
        }, min_age=30) is None

    def test_non_dict_skipped(self):
        assert _classify_discount("nope", 30) is None


class TestDiscover:

    def test_empty(self):
        with patch(
            "core.automation.discoverers.discount_cleanup."
            "_fetch_discounts",
            return_value=[],
        ):
            r = discover_discount_cleanup()
        assert r.ok
        assert r.payload == []

    def test_discounts_become_payload(self):
        discs = [
            {
                "id": "gid://shopify/Discount/1",
                "code": "OLD",
                "status": "active",
                "created_at": _aged_iso(60),
                "usage_count": 0,
            },
            {
                "id": "gid://shopify/Discount/2",
                "code": "NEW",
                "status": "active",
                "created_at": _aged_iso(5),
                "usage_count": 0,
            },
        ]
        with patch(
            "core.automation.discoverers.discount_cleanup."
            "_fetch_discounts",
            return_value=discs,
        ):
            r = discover_discount_cleanup()
        assert len(r.payload) == 1
        assert r.payload[0]["code"] == "OLD"
        assert r.payload[0]["action"] == "deactivate"

    def test_skips_missing_id_or_code(self):
        with patch(
            "core.automation.discoverers.discount_cleanup."
            "_fetch_discounts",
            return_value=[{
                "id": "",
                "code": "X",
                "status": "active",
                "created_at": _aged_iso(100),
                "usage_count": 0,
            }],
        ):
            r = discover_discount_cleanup()
        assert r.payload == []

    def test_fetch_raise_captured(self):
        def explode(*args, **kwargs):
            raise RuntimeError("api gone")
        with patch(
            "core.automation.discoverers.discount_cleanup."
            "_fetch_discounts",
            side_effect=explode,
        ):
            r = discover_discount_cleanup()
        assert not r.ok
        assert "api gone" in r.error


class TestEnvKnobs:

    def test_limit_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_DISCOUNT_CLEANUP_DISCOVER_LIMIT",
            raising=False,
        )
        assert _limit() == 100

    def test_min_age_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_DISCOUNT_CLEANUP_MIN_AGE_DAYS",
            raising=False,
        )
        assert _min_age_days() == 30
