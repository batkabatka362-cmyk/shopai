"""Tests for the enriched ``shopai store status`` command.

The original version showed only product / order / customer
counts. This adds:

  - Niche, store_type, is_active flag
  - Last-sync recency (when, status, age string)
  - ``--json`` envelope for automation

Tests cover both render modes + the no-store / sync-probe-
failure edge cases.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(store_id=None, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_store_manager(
    *,
    active="test-store",
    shop_url="example.myshopify.com",
    niche="beauty",
    store_type="dropshipping",
    is_active=True,
    products=42,
    orders=10,
    customers=15,
    revenue=999.99,
):
    sm = MagicMock()
    sm.active_store_id = active
    sm.get_stats.return_value = {
        "products": products,
        "orders": orders,
        "customers": customers,
        "total_revenue": revenue,
    }
    sm.get_store.return_value = {
        "shop_url": shop_url,
        "niche": niche,
        "store_type": store_type,
        "is_active": is_active,
    }
    return sm


def _fake_sync_status(store_id, *, age_seconds=120.0,
                     status="success"):
    """Return a sync_status dict shaped like SyncService.get_status()."""
    last_sync = time.time() - age_seconds
    return {
        "stores": [
            {
                "store_id": store_id,
                "last_sync": last_sync,
                "last_status": status,
            },
        ],
    }


# ─── Text render ─────────────────────────────────────────────


class TestTextRender:

    def test_renders_niche_type_and_counts(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store")
            )
            out, code = _capture(
                cli._cmd_store_status, _ns(store_id="test-store"),
            )
        assert code == 0
        # New fields surface
        assert "Niche:" in out
        assert "beauty" in out
        assert "Type:" in out
        assert "dropshipping" in out
        # Existing fields preserved
        assert "Products:  42" in out
        assert "Customers: 15" in out
        assert "$999.99" in out

    def test_active_marker_renders(self, cli):
        sm = _fake_store_manager(is_active=True)
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, _ = _capture(
                cli._cmd_store_status,
                _ns(store_id="test-store"),
            )
        assert "Active:    yes" in out

    def test_last_sync_recent_renders_human_readable(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store", age_seconds=120.0)
            )
            out, _ = _capture(
                cli._cmd_store_status,
                _ns(store_id="test-store"),
            )
        # 120 seconds = "2m ago"
        assert "Last sync: 2m ago (success)" in out

    def test_last_sync_never(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = {
                "stores": [],
            }
            out, _ = _capture(
                cli._cmd_store_status,
                _ns(store_id="test-store"),
            )
        assert "Last sync: never" in out


# ─── JSON envelope ───────────────────────────────────────────


class TestJsonEnvelope:

    def test_envelope_shape(self, cli):
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync_status("test-store")
            )
            out, code = _capture(
                cli._cmd_store_status,
                _ns(store_id="test-store", json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["store_id"] == "test-store"
        assert data["shop_url"] == "example.myshopify.com"
        assert data["niche"] == "beauty"
        assert data["store_type"] == "dropshipping"
        assert data["is_active"] is True
        assert data["stats"]["products"] == 42
        assert data["stats"]["customers"] == 15
        assert data["stats"]["total_revenue"] == 999.99
        # Sync fields
        assert data["last_sync_at"] is not None
        assert data["last_sync_status"] == "success"
        assert data["last_sync_age_seconds"] is not None

    def test_no_store_json_envelope(self, cli):
        sm = MagicMock()
        sm.active_store_id = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_store_status, _ns(json=True),
            )
        data = json.loads(out)
        assert data["status"] == "error"
        assert data["error"] == "no_store_selected"


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_sync_service_failure_doesnt_break(self, cli):
        """A broken SyncService probe surfaces null sync fields
        but doesn't crash the status command."""
        sm = _fake_store_manager()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
            side_effect=RuntimeError("sync down"),
        ):
            out, code = _capture(
                cli._cmd_store_status,
                _ns(store_id="test-store", json=True),
            )
        assert code == 0
        data = json.loads(out)
        # Other fields populated
        assert data["store_id"] == "test-store"
        # Sync fields null on probe failure
        assert data["last_sync_at"] is None
        assert data["last_sync_age_seconds"] is None

    def test_text_mode_no_active_unchanged(self, cli):
        """Text mode preserves the original no-store message."""
        sm = MagicMock()
        sm.active_store_id = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, _ = _capture(
                cli._cmd_store_status, _ns(),
            )
        assert "No store selected" in out

    def test_missing_store_record_doesnt_crash(self, cli):
        """If get_store returns None / empty dict, status still
        renders with placeholder values."""
        sm = MagicMock()
        sm.active_store_id = "test-store"
        sm.get_stats.return_value = {
            "products": 0, "orders": 0,
            "customers": 0, "total_revenue": 0.0,
        }
        sm.get_store.return_value = None
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = {
                "stores": [],
            }
            out, code = _capture(
                cli._cmd_store_status,
                _ns(store_id="test-store"),
            )
        # Doesn't crash
        assert code == 0
        assert "Store: test-store" in out
