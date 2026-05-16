"""Tests for ``shopai daily-brief`` -- empire-scale operator
summary combining per-store stats + per-engine activity +
pending approvals + alerts.

Pure consumer of StoreManager + SyncService + ApprovalQueue.
No live Shopify probe; designed to be cron-able.

Covers:

  - Per-store row population
  - Engine activity windowing (in-window vs out-of-window)
  - Pending counts surface separately from executed/failed
  - Alerts: sync_stale / never_synced / pending_overflow / recent_failures
  - Totals roll up correctly
  - JSON envelope shape
  - Empty fleet renders cleanly
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
    defaults = dict(window_hours=24, json=False)
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm(stores, stats_by_id=None):
    sm = MagicMock()
    sm.list_stores.return_value = stores
    sm.get_stats.side_effect = lambda sid: (
        (stats_by_id or {}).get(sid, {})
    )
    return sm


def _fake_sync(by_store_age):
    return {
        "stores": [
            {
                "store_id": sid,
                "last_sync": time.time() - age,
                "last_status": "success",
            }
            for sid, age in by_store_age.items()
        ],
    }


def _fake_action(*, engine, status, decided_at=None):
    a = MagicMock()
    a.engine = engine
    a.status = MagicMock(value=status)
    a.decided_at = decided_at if decided_at is not None else time.time() - 60
    a.proposed_at = a.decided_at
    return a


def _fake_queue(*, actions_by_status=None, stats_by_engine=None):
    q = MagicMock()
    actions_by_status = actions_by_status or {}

    def _list(status, *, engine=None, limit=500):
        return list(actions_by_status.get(status.value, []))[:limit]

    q.list_by_status.side_effect = _list
    q.stats_by_engine.return_value = stats_by_engine or {}
    return q


# ─── Empty fleet ─────────────────────────────────────────────


class TestEmptyFleet:

    def test_text_renders_zero(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out = _capture(cli._cmd_daily_brief, _ns())
        assert "0 store(s)" in out
        assert "Alerts: (none)" in out

    def test_json_zero_totals(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        assert data["totals"]["stores"] == 0
        assert data["stores"] == []
        assert data["alerts"] == []


# ─── Per-store rows + totals ─────────────────────────────────


class TestStoresAndTotals:

    def test_rows_and_totals(self, cli):
        sm = _fake_sm(
            [
                {"store_id": "a", "shop_url": "x", "niche": "n",
                 "store_type": "t", "is_active": True},
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
        ) as sync_cls, patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            sync_cls.return_value.get_status.return_value = (
                _fake_sync({"a": 60.0, "b": 3600.0})
            )
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        assert data["totals"]["stores"] == 2
        assert data["totals"]["orders"] == 20
        assert data["totals"]["revenue"] == 300.0


# ─── Engine activity windowing ───────────────────────────────


class TestEngineWindow:

    def test_within_window_counted_out_of_window_dropped(self, cli):
        from core.approval.queue import ApprovalStatus

        now = time.time()
        sm = _fake_sm([])
        q = _fake_queue(actions_by_status={
            "executed": [
                _fake_action(
                    engine="loyalty", status="executed",
                    decided_at=now - 3600,  # 1h ago → in 24h window
                ),
                _fake_action(
                    engine="loyalty", status="executed",
                    decided_at=now - 86400 * 2,  # 2 days ago → out
                ),
            ],
            "failed": [
                _fake_action(
                    engine="loyalty", status="failed",
                    decided_at=now - 1800,  # 30 min ago → in
                ),
            ],
        })
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        assert data["engine_activity"]["loyalty"]["executed"] == 1
        assert data["engine_activity"]["loyalty"]["failed"] == 1

    def test_pending_surfaces_separately(self, cli):
        sm = _fake_sm([])
        q = _fake_queue(
            stats_by_engine={
                "loyalty": {"pending": 4, "executed": 5},
                "cart_recovery": {"pending": 2, "executed": 3},
            },
        )
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        assert data["pending_by_engine"]["loyalty"] == 4
        assert data["pending_by_engine"]["cart_recovery"] == 2
        assert data["totals"]["pending"] == 6


# ─── Alerts ──────────────────────────────────────────────────


class TestAlerts:

    def test_sync_stale_alert(self, cli):
        sm = _fake_sm([
            {"store_id": "stale", "shop_url": "x",
             "niche": "n", "store_type": "t", "is_active": True},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            sync_cls.return_value.get_status.return_value = (
                _fake_sync({"stale": 86400.0 * 3})  # 3 days
            )
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        kinds = {a["kind"] for a in data["alerts"]}
        assert "sync_stale" in kinds

    def test_never_synced_alert(self, cli):
        sm = _fake_sm([
            {"store_id": "ghost", "shop_url": "x",
             "niche": "n", "store_type": "t", "is_active": False},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            sync_cls.return_value.get_status.return_value = {"stores": []}
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        kinds = {a["kind"] for a in data["alerts"]}
        assert "never_synced" in kinds

    def test_pending_overflow_alert(self, cli):
        sm = _fake_sm([])
        q = _fake_queue(stats_by_engine={
            "loyalty": {"pending": 10},
        })
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        kinds = {a["kind"] for a in data["alerts"]}
        assert "pending_overflow" in kinds

    def test_recent_failures_alert(self, cli):
        from core.approval.queue import ApprovalStatus
        now = time.time()
        sm = _fake_sm([])
        q = _fake_queue(actions_by_status={
            "failed": [
                _fake_action(
                    engine="broken_engine", status="failed",
                    decided_at=now - 60,
                ) for _ in range(4)
            ],
        })
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue", return_value=q,
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        alerts = [a for a in data["alerts"] if a["kind"] == "recent_failures"]
        assert alerts
        assert alerts[0]["engine"] == "broken_engine"

    def test_no_alerts_on_clean_fleet(self, cli):
        now = time.time()
        sm = _fake_sm([
            {"store_id": "ok", "shop_url": "x",
             "niche": "n", "store_type": "t", "is_active": True},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
        ) as sync_cls, patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            sync_cls.return_value.get_status.return_value = (
                _fake_sync({"ok": 3600.0})  # 1h ago - fresh
            )
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        assert data["alerts"] == []


# ─── Resilience ──────────────────────────────────────────────


class TestResilience:

    def test_sync_service_failure_doesnt_break(self, cli):
        sm = _fake_sm([
            {"store_id": "a", "shop_url": "x",
             "niche": "n", "store_type": "t", "is_active": True},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "data_pipeline.store.sync_service.SyncService",
            side_effect=RuntimeError("sync down"),
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        # Store row still rendered, age is None
        assert len(data["stores"]) == 1
        assert data["stores"][0]["last_sync_age_seconds"] is None

    def test_queue_failure_doesnt_break(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            side_effect=RuntimeError("queue down"),
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        # No engine activity, no pending, no failure alerts
        assert data["engine_activity"] == {}
        assert data["pending_by_engine"] == {}
