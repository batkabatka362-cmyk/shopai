"""Tests for engines.agi_earnings_history — W963-50."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from engines.agi_earnings_history import (
    AgiEarningsHistoryEngine,
)
from engines.agi_earnings_history import store as store_mod


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    with patch.object(
        store_mod, "_is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture
def _tmp_store(tmp_path):
    p = tmp_path / "agi_history.json"
    with patch.object(store_mod, "_DATA_PATH", p):
        yield p


# ── store ─────────────────────────────────────────────────


class TestStore:
    def test_record_persists(self, _tmp_store):
        ok = store_mod.record_snapshot({
            "verdict": "earning",
            "gross_profit": 100.0,
            "attribution_pct": 50.0,
        })
        assert ok is True
        assert store_mod.snapshot_count() == 1

    def test_record_non_dict_rejected(self, _tmp_store):
        assert store_mod.record_snapshot("nope") is False

    def test_query_newest_first(self, _tmp_store):
        # Insert out-of-order
        now = time.time()
        store_mod.record_snapshot({
            "ts": now - 100, "verdict": "earning",
        })
        store_mod.record_snapshot({
            "ts": now - 10, "verdict": "earning",
        })
        store_mod.record_snapshot({
            "ts": now - 50, "verdict": "organic_only",
        })
        snaps = store_mod.query(days=30, limit=10)
        # Newest first by ts
        assert (
            snaps[0]["ts"] > snaps[1]["ts"] > snaps[2]["ts"]
        )

    def test_query_window(self, _tmp_store):
        now = time.time()
        store_mod.record_snapshot({
            "ts": now - 86400 * 5, "verdict": "earning",
        })
        store_mod.record_snapshot({
            "ts": now - 86400 * 50, "verdict": "earning",
        })
        snaps = store_mod.query(days=7, limit=10)
        assert len(snaps) == 1

    def test_query_limit(self, _tmp_store):
        for _ in range(5):
            store_mod.record_snapshot({
                "verdict": "earning",
            })
        snaps = store_mod.query(days=30, limit=2)
        assert len(snaps) == 2

    def test_latest(self, _tmp_store):
        store_mod.record_snapshot({"verdict": "earning"})
        latest = store_mod.latest()
        assert latest is not None
        assert latest["verdict"] == "earning"

    def test_latest_empty(self, _tmp_store):
        assert store_mod.latest() is None

    def test_compute_trend_no_data(self, _tmp_store):
        t = store_mod.compute_trend(days=14)
        assert t["verdict"] == "no_data"

    def test_compute_trend_improving(self, _tmp_store):
        # Older snapshots: organic_only (rank 1)
        # Newer snapshots: earning (rank 3) → improving
        now = time.time()
        for i in range(4):
            store_mod.record_snapshot({
                "ts": now - 86400 * (10 - i),
                "verdict": "organic_only",
            })
        for i in range(4):
            store_mod.record_snapshot({
                "ts": now - 86400 * (3 - i),
                "verdict": "earning",
            })
        t = store_mod.compute_trend(days=30)
        assert t["verdict"] == "improving"
        assert t["delta"] > 0

    def test_compute_trend_declining(self, _tmp_store):
        now = time.time()
        for i in range(4):
            store_mod.record_snapshot({
                "ts": now - 86400 * (10 - i),
                "verdict": "earning",
            })
        for i in range(4):
            store_mod.record_snapshot({
                "ts": now - 86400 * (3 - i),
                "verdict": "organic_only",
            })
        t = store_mod.compute_trend(days=30)
        assert t["verdict"] == "declining"
        assert t["delta"] < 0

    def test_compute_trend_flat(self, _tmp_store):
        now = time.time()
        for i in range(6):
            store_mod.record_snapshot({
                "ts": now - 86400 * (10 - i),
                "verdict": "earning",
            })
        t = store_mod.compute_trend(days=30)
        assert t["verdict"] == "flat"

    def test_record_bounded(self, _tmp_store):
        # Force the cap to a small number for the test
        with patch.object(store_mod, "_MAX_ENTRIES", 3):
            for _ in range(5):
                store_mod.record_snapshot({
                    "verdict": "earning",
                })
            assert store_mod.snapshot_count() == 3


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = AgiEarningsHistoryEngine().run({})
        assert r["status"] == "success"

    def test_none_success(self):
        r = AgiEarningsHistoryEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = AgiEarningsHistoryEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = AgiEarningsHistoryEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = AgiEarningsHistoryEngine().run({})
        assert (
            r["meta"]["engine"] == "agi_earnings_history"
        )

    def test_invalid_action(self):
        r = AgiEarningsHistoryEngine().run({
            "data": {"action": "bogus"},
        })
        assert r["status"] == "error"

    def test_summary_action(self):
        r = AgiEarningsHistoryEngine().run({
            "data": {"action": "summary"},
        })
        assert r["status"] == "success"
        assert r["data"]["action"] == "summary"

    def test_query_action(self, _tmp_store):
        r = AgiEarningsHistoryEngine().run({
            "data": {"action": "query", "days": 7},
        })
        assert r["status"] == "success"
        assert r["data"]["count"] == 0

    def test_trend_action(self, _tmp_store):
        r = AgiEarningsHistoryEngine().run({
            "data": {"action": "trend", "days": 14},
        })
        assert r["status"] == "success"
        assert r["data"]["trend"]["verdict"] == "no_data"

    def test_record_action(self, _tmp_store):
        r = AgiEarningsHistoryEngine().run({
            "data": {"action": "record", "days": 7},
        })
        assert r["status"] == "success"
        assert r["data"]["action"] == "record"

    def test_invalid_days_falls_back(self):
        r = AgiEarningsHistoryEngine().run({
            "data": {
                "action": "query", "days": "abc",
            },
        })
        assert r["status"] == "success"
