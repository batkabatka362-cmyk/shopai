"""Tests for Phase 12.B inventory autonomy (W132-137)."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engines.inventory_autonomy.inventory_log import (
    InventoryEvent,
)
from engines.inventory_autonomy.inventory_applier import (
    apply_inventory_reorders,
)


def _ok():
    return SimpleNamespace(ok=True, data={}, error=None)


def _fail(error="no adapter"):
    return SimpleNamespace(ok=False, data=None, error=error)


class TestInventoryApplierSafety:

    def test_paused_skips(self):
        with patch(
            "engines.inventory_autonomy.inventory_applier."
            "is_paused",
            return_value=True,
        ):
            out = apply_inventory_reorders([
                {
                    "sku": "SKU1", "location_id": "L1",
                    "action": "reorder",
                    "prior_quantity": 0,
                    "new_quantity": 100,
                },
            ])
        assert out[0]["status"] == "paused"

    def test_not_actionable_skipped(self):
        with patch(
            "engines.inventory_autonomy.inventory_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_inventory_reorders([
                {"sku": "SKU1", "action": "browse"},
            ])
        assert out[0]["status"] == "not_actionable"

    def test_missing_ids_skipped(self):
        with patch(
            "engines.inventory_autonomy.inventory_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_inventory_reorders([
                {"sku": "", "action": "reorder",
                 "new_quantity": 50},
                {"sku": "SKU1", "location_id": "",
                 "action": "reorder", "new_quantity": 50},
                {"sku": "SKU1", "location_id": "L1",
                 "action": "reorder", "new_quantity": 0},
            ])
        for row in out:
            assert row["status"] == "missing_or_invalid_ids"

    def test_exceeds_max_quantity(self):
        with patch(
            "engines.inventory_autonomy.inventory_applier."
            "is_paused",
            return_value=False,
        ):
            out = apply_inventory_reorders([
                {
                    "sku": "SKU1", "location_id": "L1",
                    "action": "reorder",
                    "prior_quantity": 10,
                    "new_quantity": 999999,
                },
            ], max_quantity=10000)
        assert out[0]["status"] == "exceeds_max_quantity"
        assert "999999" in out[0]["error"]

    def test_delta_too_small_skipped(self):
        with patch(
            "engines.inventory_autonomy.inventory_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.inventory_autonomy.inventory_applier."
            "_get_router",
            return_value=MagicMock(),
        ), patch(
            "engines.inventory_autonomy.inventory_applier."
            "_capability",
            return_value=object(),
        ):
            out = apply_inventory_reorders([
                {
                    "sku": "SKU1", "location_id": "L1",
                    "action": "reorder",
                    "prior_quantity": 10,
                    "new_quantity": 10,
                },
            ], min_delta=1)
        assert out[0]["status"] == "delta_too_small"

    def test_happy_path(self):
        fake_router = MagicMock()
        fake_router.execute.return_value = _ok()
        with patch(
            "engines.inventory_autonomy.inventory_applier."
            "is_paused",
            return_value=False,
        ), patch(
            "engines.inventory_autonomy.inventory_applier."
            "_get_router",
            return_value=fake_router,
        ), patch(
            "engines.inventory_autonomy.inventory_applier."
            "_capability",
            return_value=object(),
        ), patch(
            "engines.inventory_autonomy.inventory_applier."
            "record_writeback",
        ), patch(
            "engines.inventory_autonomy.inventory_applier."
            "record_inventory_event",
        ):
            out = apply_inventory_reorders([
                {
                    "sku": "SKU1", "location_id": "L1",
                    "store_id": "store_a",
                    "action": "reorder",
                    "prior_quantity": 5,
                    "new_quantity": 100,
                },
            ])
        assert out[0]["applied"] is True
        assert out[0]["status"] == "recorded"


class TestInventoryWrappers:

    def test_log_event_dataclass(self):
        e = InventoryEvent(sku="SKU1", new_quantity=100)
        assert e.sku == "SKU1"
        assert e.recorded_at > 0

    def test_health_env_prefix_inventory(self, monkeypatch):
        """SHOPAI_INVENTORY_HEALTH_MIN_SAMPLE drives min."""
        monkeypatch.setenv(
            "SHOPAI_INVENTORY_HEALTH_MIN_SAMPLE", "99",
        )
        from engines.inventory_autonomy.inventory_health import (
            analyze_inventory_health,
        )
        with patch(
            "engines.inventory_autonomy.inventory_log."
            "recent_events",
            return_value=[
                {
                    "applied": False,
                    "status": "adapter_failed",
                    "recorded_at": __import__("time").time(),
                }
                for _ in range(10)
            ],
        ), patch(
            "engines.inventory_autonomy.inventory_state."
            "is_paused",
            return_value=False,
        ):
            r = analyze_inventory_health()
        assert r.verdict == "healthy"
