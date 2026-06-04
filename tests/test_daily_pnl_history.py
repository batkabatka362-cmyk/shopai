"""Tests for engines.daily_pnl_history — W963-46."""
from __future__ import annotations

import time
from unittest.mock import patch

from engines.daily_pnl_history import DailyPnlHistoryEngine
from engines.daily_pnl_history import store as store_mod


def _make_snapshot(
    store_id="s1",
    gross_profit=100.0,
    ts=None,
):
    return {
        "store_id": store_id,
        "ts": ts if ts is not None else time.time(),
        "gross_revenue": 200.0,
        "refunds": 0.0,
        "net_revenue": 200.0,
        "ad_spend": 50.0,
        "esp_spend": 0.01,
        "shipping_cost": 0.0,
        "total_cost": 50.01,
        "gross_profit": gross_profit,
        "margin_pct": 50.0,
        "order_count": 2,
        "verdict": "profitable",
        "days": 7,
    }


# ── store module ──────────────────────────────────────────


class TestStore:
    def test_empty_default(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        assert store_mod.snapshot_count() == 0
        assert store_mod.stores_with_history() == []

    def test_record_blocked_in_test_env(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        assert store_mod.record_snapshot(
            _make_snapshot(),
        ) is False

    def test_record_invalid_blocked(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            assert store_mod.record_snapshot(
                "not-a-dict",
            ) is False
            assert store_mod.record_snapshot({}) is False

    def test_record_persists(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            ok = store_mod.record_snapshot(
                _make_snapshot(),
            )
        assert ok is True
        assert store_mod.snapshot_count() == 1

    def test_record_auto_tags_date(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        ts = time.time()
        snap = {"store_id": "s1", "gross_profit": 5.0}
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record_snapshot(snap)
        out = store_mod.query(store_id="s1", days=30)
        assert "date" in out[0]
        assert "ts" in out[0]

    def test_query_filters_by_store(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record_snapshot(
                _make_snapshot(store_id="s1"),
            )
            store_mod.record_snapshot(
                _make_snapshot(store_id="s2"),
            )
        s1 = store_mod.query(store_id="s1", days=30)
        s2 = store_mod.query(store_id="s2", days=30)
        any_ = store_mod.query(days=30)
        assert len(s1) == 1
        assert len(s2) == 1
        assert len(any_) == 2

    def test_query_filters_by_window(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        now = time.time()
        old_ts = now - 60 * 86400  # 60 days ago
        recent_ts = now - 5 * 86400
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record_snapshot(
                _make_snapshot(ts=old_ts),
            )
            store_mod.record_snapshot(
                _make_snapshot(ts=recent_ts),
            )
        recent = store_mod.query(
            store_id="s1", days=30, now=now,
        )
        assert len(recent) == 1

    def test_query_newest_first(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        now = time.time()
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record_snapshot(
                _make_snapshot(ts=now - 5 * 86400),
            )
            store_mod.record_snapshot(
                _make_snapshot(ts=now - 1 * 86400),
            )
            store_mod.record_snapshot(
                _make_snapshot(ts=now - 3 * 86400),
            )
        out = store_mod.query(
            store_id="s1", days=30, now=now,
        )
        # Newest (1 day ago) first
        assert out[0]["ts"] == now - 1 * 86400

    def test_compute_trend_no_data(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        t = store_mod.compute_trend(store_id="s1")
        assert t["verdict"] == "no_data"

    def test_compute_trend_too_few_samples(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            for _ in range(3):
                store_mod.record_snapshot(_make_snapshot())
        t = store_mod.compute_trend(store_id="s1")
        assert t["verdict"] == "no_data"

    def test_compute_trend_rising(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        now = time.time()
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            # 4 snapshots: first half low profit,
            # second half high
            for i, p in enumerate([10, 20, 80, 100]):
                store_mod.record_snapshot(
                    _make_snapshot(
                        gross_profit=p,
                        ts=now - (4 - i) * 86400,
                    ),
                )
        t = store_mod.compute_trend(
            store_id="s1", days=30, now=now,
        )
        assert t["verdict"] == "rising"
        assert t["delta"] > 0

    def test_compute_trend_falling(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        now = time.time()
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            for i, p in enumerate([100, 80, 20, 10]):
                store_mod.record_snapshot(
                    _make_snapshot(
                        gross_profit=p,
                        ts=now - (4 - i) * 86400,
                    ),
                )
        t = store_mod.compute_trend(
            store_id="s1", days=30, now=now,
        )
        assert t["verdict"] == "falling"
        assert t["delta"] < 0

    def test_compute_trend_flat(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        now = time.time()
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            for i, p in enumerate([
                50.0, 50.5, 50.2, 50.3,
            ]):
                store_mod.record_snapshot(
                    _make_snapshot(
                        gross_profit=p,
                        ts=now - (4 - i) * 86400,
                    ),
                )
        t = store_mod.compute_trend(
            store_id="s1", days=30, now=now,
        )
        assert t["verdict"] == "flat"


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        # Default action is summary
        r = DailyPnlHistoryEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = DailyPnlHistoryEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = DailyPnlHistoryEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = DailyPnlHistoryEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_unknown_action_error(self):
        r = DailyPnlHistoryEngine().run({
            "data": {"action": "blast"},
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = DailyPnlHistoryEngine().run({})
        assert r["meta"]["engine"] == "daily_pnl_history"


class TestActions:
    def test_summary_default(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        r = DailyPnlHistoryEngine().run({})
        assert r["data"]["action"] == "summary"
        assert r["data"]["total_snapshots"] == 0

    def test_record_invokes_pnl_tracker(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        # We can't actually write under pytest -- verify the
        # mechanism is wired even though wrote==False.
        with patch(
            "engines.store_pnl_tracker.tracker."
            "compute_fleet_pnl",
        ) as fleet_mock, patch(
            "engines.store_pnl_tracker.tracker."
            "compute_store_pnl",
        ) as store_mock:
            # Fleet returns 2 stores
            from engines.store_pnl_tracker.tracker import (
                FleetPnlReport, StorePnl,
            )
            fleet_mock.return_value = FleetPnlReport(
                days=7,
                by_store=[
                    StorePnl(store_id="s1", days=7),
                    StorePnl(store_id="s2", days=7),
                ],
            )
            store_mock.return_value = StorePnl(
                store_id="s1", days=7,
                gross_profit=100.0,
                verdict="profitable",
            )
            r = DailyPnlHistoryEngine().run({
                "data": {"action": "record"},
            })
        assert r["data"]["store_count"] == 2
        # wrote_count is 0 under pytest (Pattern J)

    def test_query_action(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record_snapshot(_make_snapshot())
        r = DailyPnlHistoryEngine().run({
            "data": {
                "action": "query",
                "store_id": "s1",
                "days": 30,
            },
        })
        assert r["data"]["count"] == 1

    def test_trend_single_store(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        now = time.time()
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            for i, p in enumerate([10, 20, 80, 100]):
                store_mod.record_snapshot(
                    _make_snapshot(
                        gross_profit=p,
                        ts=now - (4 - i) * 86400,
                    ),
                )
        r = DailyPnlHistoryEngine().run({
            "data": {
                "action": "trend",
                "store_id": "s1",
            },
        })
        assert "trend" in r["data"]

    def test_trend_fleet_wide(self, tmp_path):
        store_mod.reset_path(tmp_path / "ph.json")
        with patch.object(
            store_mod, "_is_test_environment",
            return_value=False,
        ):
            store_mod.record_snapshot(
                _make_snapshot(store_id="s1"),
            )
        r = DailyPnlHistoryEngine().run({
            "data": {"action": "trend"},
        })
        assert "trends" in r["data"]
        assert r["data"]["store_count"] == 1

    def test_invalid_days_falls_back(self):
        r = DailyPnlHistoryEngine().run({
            "data": {
                "action": "query", "days": "abc",
            },
        })
        assert r["data"]["days"] == 30
