"""Tests for audit-pass-20 fixes in core/orchestrator/store_snapshot.

  1. update_customers used `o.get("customer", {}).get("id")` —
     `.get("customer", {})` returns the literal default ONLY when
     the key is missing; if the key exists with value None, .get
     returns None and the next .get("id") crashes with
     AttributeError.
  2. update_inventory used `p.get("inventory_quantity", 0)` for
     the sum, but `.get(k, 0)` returns the stored value (which
     can be None) when the key exists. `int + None` then crashed.
     Lines 98-99 already used the `or 0` pattern — this line
     was inconsistent.
  3. load() wrapped the entire load in try/except and silently
     returned an empty snapshot on JSON parse errors. The next
     persist() then overwrote the corrupted-but-recoverable file
     with empty data, destroying all snapshot history forever.
  4. persist() failures were logged-and-forgotten with no way for
     callers / tests / dashboards to detect a silent disk failure.
"""
import json
import os
import tempfile

import pytest


@pytest.fixture
def snap_path(monkeypatch, tmp_path):
    """Point the snapshot module at a fresh temp file per test."""
    import core.orchestrator.store_snapshot as ss_mod
    p = str(tmp_path / "snap.json")
    monkeypatch.setattr(ss_mod, "_SNAPSHOT_PATH", p)
    return p


# ── update_customers None handling ──────────────────────────


class TestUpdateCustomersNone:
    def test_customer_key_with_none_value_does_not_crash(self):
        """Regression: previously `o.get("customer", {}).get("id")`
        crashed when `customer` was present with None."""
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot()
        # Order with customer=None — common when Shopify returns
        # a guest checkout
        orders = [
            {"customer": None, "id": 1},
            {"customer": None, "id": 2},
            {"customer_id": 42},
            {"customer": {"id": 99}},
        ]
        customers = [{"id": 42}, {"id": 99}, {"id": 1}, {"id": 2}]
        # Should not raise
        snap.update_customers(customers, orders)
        # Active = customers 42 + 99 = 2; inactive = 2
        assert snap.customers["active_recent"] == 2
        assert snap.customers["inactive"] == 2

    def test_non_dict_order_skipped(self):
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot()
        snap.update_customers(
            [{"id": 1}],
            [None, "bad", {"customer_id": 1}],
        )
        assert snap.customers["active_recent"] == 1


# ── update_inventory None handling ──────────────────────────


class TestUpdateInventoryNone:
    def test_none_inventory_quantity_does_not_crash(self):
        """Regression: previously `sum(p.get("inventory_quantity",
        0))` crashed when the key was present with None."""
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot()
        snap.update_inventory([
            {"id": 1, "inventory_quantity": 5},
            {"id": 2, "inventory_quantity": None},   # the bad one
            {"id": 3, "inventory_quantity": 10},
        ])
        assert snap.inventory["total_units"] == 15
        assert snap.inventory["total_products"] == 3


# ── load() corrupted file backup ─────────────────────────────


class TestLoadCorruptedBackup:
    def test_corrupt_json_moved_aside(self, snap_path):
        """Regression: previously corrupted JSON was silently
        ignored and the next persist() overwrote it with empty
        data, destroying the original."""
        with open(snap_path, "w") as f:
            f.write("not valid json {{{")
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot.load()
        # Empty snapshot returned (graceful fallback)
        assert snap.financial == {}
        # Original file moved aside, NOT just deleted or
        # left for the next persist() to overwrite
        assert not os.path.exists(snap_path)
        directory = os.path.dirname(snap_path) or "."
        backups = [f for f in os.listdir(directory) if "corrupted" in f]
        assert len(backups) == 1

    def test_non_dict_snapshot_treated_as_corrupt(self, snap_path):
        with open(snap_path, "w") as f:
            json.dump([1, 2, 3], f)  # valid JSON, wrong shape
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot.load()
        assert snap.financial == {}
        directory = os.path.dirname(snap_path) or "."
        backups = [f for f in os.listdir(directory) if "corrupted" in f]
        assert len(backups) == 1

    def test_missing_file_returns_empty_snapshot(self, snap_path):
        # File doesn't exist → empty snapshot, no backup created
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot.load()
        assert snap.financial == {}

    def test_valid_snapshot_round_trips(self, snap_path):
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot()
        snap.financial = {"net_profit": 100}
        snap.products = {"decision": "raise"}
        snap.finalize("cycle_x")
        snap.persist()
        # Reload
        loaded = StoreSnapshot.load()
        assert loaded.financial["net_profit"] == 100
        assert loaded.products["decision"] == "raise"
        assert loaded.cycle_id == "cycle_x"


# ── Persist error tracking ──────────────────────────────────


class TestPersistErrorTracking:
    def test_persist_failure_recorded(self, snap_path, monkeypatch):
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot()
        # Force makedirs to raise so persist falls into except
        import core.orchestrator.store_snapshot as ss_mod
        monkeypatch.setattr(
            ss_mod.os, "makedirs",
            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")),
        )
        snap.persist()
        err = snap.get_persist_error()
        assert "OSError" in err
        assert "disk full" in err

    def test_successful_persist_clears_error(self, snap_path):
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot()
        snap._last_persist_error = "stale error"
        snap.persist()  # should reset
        assert snap.get_persist_error() == ""

    def test_get_persist_error_default_empty(self):
        from core.orchestrator.store_snapshot import StoreSnapshot
        snap = StoreSnapshot()
        # Never persisted yet — error string is empty
        assert snap.get_persist_error() == ""
