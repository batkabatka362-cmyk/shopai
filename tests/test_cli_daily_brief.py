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


# ─── Transfer activity section ───────────────────────────────


def _fake_queue_with_transfers(rows, outcomes=None):
    """Build a queue that exposes ``_conn`` with the transfer
    rows used by the daily-brief transfer-activity probe.

    Each row is a dict with id/status/proposed_at; outcomes is
    optional ``{id: [{polarity, metrics}, ...]}``.
    """
    outcomes = outcomes or {}
    q = MagicMock()

    # Existing daily-brief paths (list_by_status / stats_by_engine).
    q.list_by_status.side_effect = lambda *a, **kw: []
    q.stats_by_engine.return_value = {}

    fake_conn = MagicMock()
    fake_conn.__enter__ = lambda self: self
    fake_conn.__exit__ = lambda *a: None
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = rows
    fake_conn.execute.return_value = fake_cursor
    q._conn = fake_conn
    q.get_outcomes.side_effect = lambda aid: outcomes.get(aid, [])
    return q


class TestTransferActivitySection:

    def test_no_transfers_in_window(self, cli):
        """Empty transfer scan → all counters at zero, but the
        section still appears in the JSON envelope."""
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue_with_transfers([]),
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        assert "transfer_activity" in data
        assert data["transfer_activity"]["applied_in_window"] == 0
        assert data["transfer_activity"]["positive_outcomes"] == 0

    def test_mixed_status_transfers_counted(self, cli):
        sm = _fake_sm([])
        rows = [
            {"id": "t1", "status": "executed",
             "proposed_at": time.time() - 3600.0},
            {"id": "t2", "status": "executed",
             "proposed_at": time.time() - 7200.0},
            {"id": "t3", "status": "pending",
             "proposed_at": time.time() - 1800.0},
            {"id": "t4", "status": "failed",
             "proposed_at": time.time() - 900.0},
            {"id": "t5", "status": "rejected",
             "proposed_at": time.time() - 600.0},
        ]
        outcomes = {
            "t1": [
                {"polarity": "positive", "metrics": {"revenue": 50.0}},
            ],
            "t2": [
                {"polarity": "negative", "metrics": {}},
            ],
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue_with_transfers(rows, outcomes),
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        ta = data["transfer_activity"]
        assert ta["applied_in_window"] == 5
        assert ta["executed"] == 2
        assert ta["pending"] == 1
        assert ta["failed"] == 1
        assert ta["rejected_or_expired"] == 1
        assert ta["positive_outcomes"] == 1
        assert ta["negative_outcomes"] == 1

    def test_text_mode_shows_transfer_section(self, cli):
        sm = _fake_sm([])
        rows = [
            {"id": "t1", "status": "executed",
             "proposed_at": time.time() - 1800.0},
        ]
        outcomes = {
            "t1": [
                {"polarity": "positive", "metrics": {"revenue": 20.0}},
            ],
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue_with_transfers(rows, outcomes),
        ):
            out = _capture(cli._cmd_daily_brief, _ns())
        assert "Cross-store transfers" in out
        assert "1 applied" in out
        assert "+1" in out

    def test_text_mode_skips_section_when_empty(self, cli):
        """Don't clutter the morning brief with a zero-row
        section when nothing was transferred in the window."""
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue_with_transfers([]),
        ):
            out = _capture(cli._cmd_daily_brief, _ns())
        assert "Cross-store transfers" not in out

    def test_outcomes_raise_doesnt_break_section(self, cli):
        """If get_outcomes raises mid-loop, the row still counts
        toward executed but polarity stays at zero (degrades
        gracefully)."""
        sm = _fake_sm([])
        rows = [
            {"id": "t1", "status": "executed",
             "proposed_at": time.time() - 1800.0},
        ]
        q = _fake_queue_with_transfers(rows)
        q.get_outcomes.side_effect = RuntimeError("outcomes table missing")
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=q,
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        ta = data["transfer_activity"]
        assert ta["executed"] == 1
        assert ta["positive_outcomes"] == 0
        assert ta["negative_outcomes"] == 0


# ─── Engine-degradation alerts integration ───────────────────


class TestEngineDegradationAlerts:
    """``daily-brief`` calls
    ``core.approval.outcome_trends.compute_engine_alerts`` and
    folds returned EngineAlerts into the ``alerts`` list as
    ``kind='engine_score_degraded'`` entries."""

    def test_no_alerts_returned_no_kind_in_alerts(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[],
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        kinds = {a.get("kind") for a in data["alerts"]}
        assert "engine_score_degraded" not in kinds

    def test_returned_alerts_added_to_envelope(self, cli):
        from core.approval.outcome_trends import EngineAlert

        fake_alert = EngineAlert(
            engine="loyalty",
            recent_executed=5,
            baseline_executed=20,
            recent_score=0.2,
            baseline_score=0.85,
            recent_polarised=5,
            baseline_polarised=18,
            drop=0.65,
            detail="20% recent vs 85% baseline (drop 65%)",
            kind="outcome_score_degraded",
        )
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[fake_alert],
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        degraded = [
            a for a in data["alerts"]
            if a.get("kind") == "engine_score_degraded"
        ]
        assert len(degraded) == 1
        assert degraded[0]["engine"] == "loyalty"
        assert "20% recent vs 85% baseline" in degraded[0]["detail"]

    def test_compute_raise_doesnt_break_daily_brief(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            side_effect=RuntimeError("queue down"),
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        kinds = {a.get("kind") for a in data["alerts"]}
        assert "engine_score_degraded" not in kinds


# ─── alert_history wiring ────────────────────────────────────


class TestAlertHistoryWiring:
    """``daily-brief`` records each alert via
    ``core.approval.alert_history.record_alerts`` and reads the
    consecutive-day count via ``consecutive_runs_per_engine``.
    Engines flagged 2+ days running get a ``consecutive_days``
    field plus an inflated ``detail`` string."""

    def _fake_alert(self, engine="loyalty"):
        from core.approval.outcome_trends import EngineAlert
        return EngineAlert(
            engine=engine,
            recent_executed=5,
            baseline_executed=20,
            recent_score=0.2,
            baseline_score=0.85,
            recent_polarised=5,
            baseline_polarised=18,
            drop=0.65,
            detail="20% recent vs 85% baseline (drop 65%)",
            kind="outcome_score_degraded",
        )

    def test_record_alerts_called_with_engine_alerts(self, cli):
        sm = _fake_sm([])
        fake_alert = self._fake_alert()
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[fake_alert],
        ), patch(
            "core.approval.alert_history.record_alerts",
        ) as record_mock, patch(
            "core.approval.alert_history."
            "consecutive_runs_per_engine",
            return_value={},
        ):
            _capture(cli._cmd_daily_brief, _ns(json=True))
        record_mock.assert_called_once()
        passed_alerts = record_mock.call_args[0][0]
        assert list(passed_alerts) == [fake_alert]

    def test_consecutive_days_attached_at_2_or_more(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[self._fake_alert("loyalty")],
        ), patch(
            "core.approval.alert_history.record_alerts",
            return_value=1,
        ), patch(
            "core.approval.alert_history."
            "consecutive_runs_per_engine",
            return_value={"loyalty": 3},
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        degraded = [
            a for a in data["alerts"]
            if a.get("kind") == "engine_score_degraded"
        ]
        assert len(degraded) == 1
        assert degraded[0]["consecutive_days"] == 3
        assert "3 day(s) running" in degraded[0]["detail"]

    def test_consecutive_days_omitted_at_1(self, cli):
        """Single-day firings shouldn't claim a streak."""
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[self._fake_alert("loyalty")],
        ), patch(
            "core.approval.alert_history.record_alerts",
            return_value=1,
        ), patch(
            "core.approval.alert_history."
            "consecutive_runs_per_engine",
            return_value={"loyalty": 1},
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        degraded = [
            a for a in data["alerts"]
            if a.get("kind") == "engine_score_degraded"
        ]
        assert len(degraded) == 1
        assert "consecutive_days" not in degraded[0]
        assert "running" not in degraded[0]["detail"]

    def test_record_alerts_raise_doesnt_break_daily_brief(
        self, cli,
    ):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[self._fake_alert()],
        ), patch(
            "core.approval.alert_history.record_alerts",
            side_effect=RuntimeError("disk full"),
        ), patch(
            "core.approval.alert_history."
            "consecutive_runs_per_engine",
            return_value={},
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        # Alert still surfaces even when recording fails.
        kinds = {a.get("kind") for a in data["alerts"]}
        assert "engine_score_degraded" in kinds

    def test_consecutive_runs_raise_doesnt_break(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[self._fake_alert()],
        ), patch(
            "core.approval.alert_history.record_alerts",
            return_value=1,
        ), patch(
            "core.approval.alert_history."
            "consecutive_runs_per_engine",
            side_effect=RuntimeError("disk full"),
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        degraded = [
            a for a in data["alerts"]
            if a.get("kind") == "engine_score_degraded"
        ]
        # Without consecutive data, no consecutive_days field --
        # but the alert still surfaces.
        assert len(degraded) == 1
        assert "consecutive_days" not in degraded[0]


class TestAutoQuarantineFromAlertsWiring:
    """``daily-brief`` calls
    ``alert_quarantine.maybe_auto_quarantine_from_alerts`` and
    surfaces each newly-paused engine as a
    ``kind='auto_alert_quarantined'`` entry."""

    def _fake_alert(self, engine="loyalty"):
        from core.approval.outcome_trends import EngineAlert
        return EngineAlert(
            engine=engine,
            recent_executed=5,
            baseline_executed=20,
            recent_score=0.2,
            baseline_score=0.85,
            recent_polarised=5,
            baseline_polarised=18,
            drop=0.65,
            detail="20% recent vs 85% baseline (drop 65%)",
            kind="outcome_score_degraded",
        )

    def test_newly_paused_surfaces_alert(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[self._fake_alert("loyalty")],
        ), patch(
            "core.approval.alert_history.record_alerts",
            return_value=1,
        ), patch(
            "core.approval.alert_history."
            "consecutive_runs_per_engine",
            return_value={"loyalty": 3},
        ), patch(
            "core.approval.alert_quarantine."
            "maybe_auto_quarantine_from_alerts",
            return_value=["loyalty"],
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        paused = [
            a for a in data["alerts"]
            if a.get("kind") == "auto_alert_quarantined"
        ]
        assert len(paused) == 1
        assert paused[0]["engine"] == "loyalty"
        assert "auto-paused" in paused[0]["detail"]

    def test_no_paused_no_alert(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[self._fake_alert("loyalty")],
        ), patch(
            "core.approval.alert_history.record_alerts",
            return_value=1,
        ), patch(
            "core.approval.alert_history."
            "consecutive_runs_per_engine",
            return_value={"loyalty": 1},
        ), patch(
            "core.approval.alert_quarantine."
            "maybe_auto_quarantine_from_alerts",
            return_value=[],
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        kinds = {a.get("kind") for a in data["alerts"]}
        assert "auto_alert_quarantined" not in kinds

    def test_bridge_raise_doesnt_break_daily_brief(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.approval.queue.get_approval_queue",
            return_value=_fake_queue(),
        ), patch(
            "core.approval.outcome_trends.compute_engine_alerts",
            return_value=[self._fake_alert()],
        ), patch(
            "core.approval.alert_history.record_alerts",
            return_value=1,
        ), patch(
            "core.approval.alert_history."
            "consecutive_runs_per_engine",
            return_value={},
        ), patch(
            "core.approval.alert_quarantine."
            "maybe_auto_quarantine_from_alerts",
            side_effect=RuntimeError("state corruption"),
        ):
            out = _capture(cli._cmd_daily_brief, _ns(json=True))
        data = json.loads(out)
        # Degraded alert still surfaces; bridge failure swallowed.
        kinds = {a.get("kind") for a in data["alerts"]}
        assert "engine_score_degraded" in kinds
        assert "auto_alert_quarantined" not in kinds
