"""Tests for inventory discoverer (Wave 831)."""
from __future__ import annotations

from unittest.mock import patch

from core.automation.discoverers.inventory import (
    _limit,
    _propose_for_level,
    _reorder_multiplier,
    _safety_stock,
    discover_inventory,
)
from core.automation.payload_discoverer import (
    discover, has_discoverer,
)


class TestRegistryWireup:

    def test_registered_after_import(self):
        assert has_discoverer("inventory")

    def test_dispatch_via_registry(self):
        with patch(
            "core.automation.discoverers.inventory."
            "_fetch_levels",
            return_value=[],
        ):
            r = discover("inventory")
        assert r.ok
        assert r.source == "shopify_inventory_levels"


class TestProposeForLevel:

    def test_below_safety_yields_row(self):
        row = _propose_for_level(
            {
                "sku": "WIDGET-001",
                "location_id": "loc1",
                "available": 2,
            },
            safety=5, multiplier=2, max_q=10000,
        )
        assert row is not None
        assert row["sku"] == "WIDGET-001"
        assert row["action"] == "reorder"
        assert row["new_quantity"] > row["prior_quantity"]

    def test_at_safety_skipped(self):
        # at safety stock should NOT trigger (only strictly below)
        row = _propose_for_level(
            {"sku": "x", "location_id": "l", "available": 10},
            safety=5, multiplier=2, max_q=10000,
        )
        assert row is None

    def test_above_safety_skipped(self):
        assert _propose_for_level(
            {"sku": "x", "location_id": "l", "available": 100},
            safety=5, multiplier=2, max_q=10000,
        ) is None

    def test_missing_sku_skipped(self):
        assert _propose_for_level(
            {"sku": "", "location_id": "l", "available": 1},
            safety=5, multiplier=2, max_q=10000,
        ) is None

    def test_missing_location_skipped(self):
        assert _propose_for_level(
            {"sku": "x", "location_id": "", "available": 1},
            safety=5, multiplier=2, max_q=10000,
        ) is None

    def test_max_clamp_half_max(self):
        row = _propose_for_level(
            {"sku": "x", "location_id": "l", "available": 0},
            safety=10_000, multiplier=10, max_q=100,
        )
        # safety * mult = 100_000; clamped to max_q/2 = 50
        assert row is not None
        assert row["new_quantity"] == 50

    def test_proposed_must_exceed_prior(self):
        row = _propose_for_level(
            {"sku": "x", "location_id": "l", "available": 100},
            safety=1, multiplier=2, max_q=10000,
        )
        # available > safety so skipped before delta check
        assert row is None

    def test_non_dict_skipped(self):
        assert _propose_for_level(
            "not a dict", 5, 2, 10_000,
        ) is None


class TestDiscover:

    def test_empty(self):
        with patch(
            "core.automation.discoverers.inventory."
            "_fetch_levels",
            return_value=[],
        ):
            r = discover_inventory()
        assert r.ok
        assert r.payload == []

    def test_levels_become_payload(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_INVENTORY_SAFETY_STOCK", raising=False,
        )
        monkeypatch.delenv(
            "SHOPAI_INVENTORY_REORDER_MULTIPLIER",
            raising=False,
        )
        levels = [
            {
                "sku": "LOW",
                "location_id": "loc1",
                "available": 1,
            },
            {
                "sku": "HIGH",
                "location_id": "loc1",
                "available": 100,
            },
        ]
        with patch(
            "core.automation.discoverers.inventory."
            "_fetch_levels",
            return_value=levels,
        ):
            r = discover_inventory()
        assert len(r.payload) == 1
        assert r.payload[0]["sku"] == "LOW"
        assert r.payload[0]["action"] == "reorder"

    def test_fetch_raise_captured(self):
        def explode(*args, **kwargs):
            raise RuntimeError("api dead")
        with patch(
            "core.automation.discoverers.inventory."
            "_fetch_levels",
            side_effect=explode,
        ):
            r = discover_inventory()
        assert not r.ok
        assert "api dead" in r.error


class TestEnvKnobs:

    def test_limit_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_INVENTORY_DISCOVER_LIMIT", raising=False,
        )
        assert _limit() == 100

    def test_safety_stock_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_INVENTORY_SAFETY_STOCK", raising=False,
        )
        assert _safety_stock() == 5

    def test_multiplier_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_INVENTORY_REORDER_MULTIPLIER",
            raising=False,
        )
        assert _reorder_multiplier() == 2

    def test_multiplier_clamped_to_2(self, monkeypatch):
        # Multiplier < 2 is nonsensical; clamp
        monkeypatch.setenv(
            "SHOPAI_INVENTORY_REORDER_MULTIPLIER", "0",
        )
        assert _reorder_multiplier() == 2
