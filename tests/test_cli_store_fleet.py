"""Tests for ``shopai store fleet`` -- cross-store summary.

Renders one row per registered store with aggregated metrics +
sync recency. Pure consumer of StoreManager + SyncService; no
AGI-stack dependency.

Covers:

  - Empty fleet (no stores configured)
  - Per-store row population from sm.list_stores + sm.get_stats
  - Sync recency joined from SyncService
  - --sort-by options
  - Totals + spotlight (freshest / stalest / never-synced)
  - --json envelope shape
  - Resilience: sync probe failure doesn't break the summary
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import time
from io import StringIO
from unittest.mock import MagicMock, patch

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
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit:
        pass
    return buf.getvalue()


def _ns(**kw):
    defaults = dict(json=False, sort_by="revenue")
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm(stores, stats_by_id=None):
    sm = MagicMock()
    sm.list_stores.return_value = stores
    sm.get_stats.side_effect = lambda sid: (
        (stats_by_id or {}).get(sid, {})
    )
    return sm


def _fake_sync(by_store):
    """Build a fake SyncService return whose stores entry matches
    the dict keys, with last_sync = now - age_seconds."""
    return {
        "stores": [
            {
                "store_id": sid,
                "last_sync": time.time() - age,
                "last_status": "success",
            }
            for sid, age in by_store.items()
        ],
    }


# ─── Empty fleet ─────────────────────────────────────────────


class TestEmptyFleet:

    def test_empty_text(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out = _capture(cli._cmd_store_fleet, _ns())
        assert "No stores configured" in out

    def test_empty_json(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out = _capture(cli._cmd_store_fleet, _ns(json=True))
        data = json.loads(out)
        assert data["stores"] == []
        assert data["totals"] == {}


# ─── Row population ──────────────────────────────────────────


class TestRowPopulation:

    def test_one_store_renders(self, cli):
        sm = _fake_sm(
            [{
                "store_id": "a",
                "shop_url": "a.myshopify.com",
                "niche": "beauty",
                "store_type": "dropshipping",
                "is_active": True,
            }],
            stats_by_id={"a": {
                "products": 42, "orders": 10,
                "customers": 5, "total_revenue": 999.99,
            }},
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync({"a": 60.0})
            )
            out = _capture(cli._cmd_store_fleet, _ns())
        assert "a " in out
        assert "beauty" in out
        assert "42" in out  # products
        assert "999.99" in out

    def test_active_marker_renders(self, cli):
        sm = _fake_sm([
            {
                "store_id": "active-1", "shop_url": "x",
                "niche": "n", "store_type": "t",
                "is_active": True,
            },
            {
                "store_id": "inactive-1", "shop_url": "y",
                "niche": "n", "store_type": "t",
                "is_active": False,
            },
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = {"stores": []}
            out = _capture(cli._cmd_store_fleet, _ns())
        # The active row carries an asterisk in front
        lines = [ln for ln in out.split("\n") if "active-1" in ln]
        assert lines
        assert "*active-1" in lines[0]


# ─── Sort order ──────────────────────────────────────────────


class TestSortOrder:

    @pytest.mark.parametrize("sort_by,expected_first", [
        ("revenue", "a"),
        ("products", "b"),
        ("orders", "a"),
        ("name", "a"),
    ])
    def test_sort_by(self, cli, sort_by, expected_first):
        sm = _fake_sm(
            [
                {
                    "store_id": "a", "shop_url": "x",
                    "niche": "n", "store_type": "t",
                    "is_active": False,
                },
                {
                    "store_id": "b", "shop_url": "y",
                    "niche": "n", "store_type": "t",
                    "is_active": False,
                },
            ],
            stats_by_id={
                "a": {"products": 1, "orders": 100,
                      "customers": 50, "total_revenue": 5000.0},
                "b": {"products": 100, "orders": 1,
                      "customers": 5, "total_revenue": 100.0},
            },
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = {"stores": []}
            out = _capture(
                cli._cmd_store_fleet, _ns(json=True, sort_by=sort_by),
            )
        data = json.loads(out)
        assert data["stores"][0]["store_id"] == expected_first


# ─── Totals + spotlight ──────────────────────────────────────


class TestTotalsAndSpotlight:

    def test_totals_sum_correctly(self, cli):
        sm = _fake_sm(
            [
                {"store_id": "a", "shop_url": "x", "niche": "n",
                 "store_type": "t", "is_active": False},
                {"store_id": "b", "shop_url": "y", "niche": "n",
                 "store_type": "t", "is_active": False},
            ],
            stats_by_id={
                "a": {"products": 10, "orders": 5,
                      "customers": 3, "total_revenue": 100.0},
                "b": {"products": 20, "orders": 15,
                      "customers": 7, "total_revenue": 200.0},
            },
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = {"stores": []}
            out = _capture(cli._cmd_store_fleet, _ns(json=True))
        data = json.loads(out)
        assert data["totals"]["stores"] == 2
        assert data["totals"]["products"] == 30
        assert data["totals"]["orders"] == 20
        assert data["totals"]["customers"] == 10
        assert data["totals"]["revenue"] == 300.0

    def test_spotlight_freshest_and_stalest(self, cli):
        sm = _fake_sm([
            {"store_id": "fresh", "shop_url": "f",
             "niche": "n", "store_type": "t",
             "is_active": False},
            {"store_id": "stale", "shop_url": "s",
             "niche": "n", "store_type": "t",
             "is_active": False},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            sync_cls.return_value.get_status.return_value = (
                _fake_sync({"fresh": 60.0, "stale": 86_400.0 * 5})
            )
            out = _capture(cli._cmd_store_fleet, _ns(json=True))
        data = json.loads(out)
        assert data["spotlight"]["freshest_sync"] == "fresh"
        assert data["spotlight"]["stalest_sync"] == "stale"

    def test_spotlight_never_synced(self, cli):
        sm = _fake_sm([
            {"store_id": "synced", "shop_url": "x",
             "niche": "n", "store_type": "t",
             "is_active": False},
            {"store_id": "ghost", "shop_url": "y",
             "niche": "n", "store_type": "t",
             "is_active": False},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls:
            # Only "synced" has a sync entry; "ghost" is missing
            sync_cls.return_value.get_status.return_value = (
                _fake_sync({"synced": 60.0})
            )
            out = _capture(cli._cmd_store_fleet, _ns(json=True))
        data = json.loads(out)
        assert "ghost" in data["spotlight"]["never_synced"]
        assert "synced" not in data["spotlight"]["never_synced"]


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_sync_service_failure_doesnt_break_summary(self, cli):
        """A broken SyncService probe surfaces age as None
        but the summary still renders."""
        sm = _fake_sm(
            [{"store_id": "a", "shop_url": "x", "niche": "n",
              "store_type": "t", "is_active": True}],
            stats_by_id={"a": {
                "products": 5, "orders": 1,
                "customers": 1, "total_revenue": 50.0,
            }},
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
            side_effect=RuntimeError("sync down"),
        ):
            out = _capture(cli._cmd_store_fleet, _ns(json=True))
        data = json.loads(out)
        assert len(data["stores"]) == 1
        assert data["stores"][0]["last_sync_age_seconds"] is None
        # Single store ends up in never_synced spotlight
        assert "a" in data["spotlight"]["never_synced"]
