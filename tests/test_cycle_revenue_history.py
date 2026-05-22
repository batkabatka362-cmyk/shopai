"""Tests for ``core.autonomous.cycle_revenue_history``."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import cycle_revenue_history as crh


@pytest.fixture
def tmp_history(tmp_path):
    path = tmp_path / "cycle_revenue_history.json"
    crh._reset_for_tests(path)
    yield path
    crh._reset_for_tests(
        Path("data/cycle_revenue_history.json"),
    )


class TestPatternJ:

    def test_default_short_circuits(self, tmp_history):
        ok = crh.record_snapshot(
            fleet_revenue=1000.0, store_count=2,
        )
        assert ok is False
        assert not tmp_history.exists()

    def test_disabled_guard_writes(self, tmp_history):
        with patch(
            "core.autonomous.cycle_revenue_history."
            "_is_test_environment",
            return_value=False,
        ):
            ok = crh.record_snapshot(
                fleet_revenue=500.0, store_count=1,
            )
        assert ok is True
        assert tmp_history.exists()


class TestRecord:

    def _w(self):
        return patch(
            "core.autonomous.cycle_revenue_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_round_trip(self, tmp_history):
        with self._w():
            crh.record_snapshot(
                fleet_revenue=1500.0, store_count=3,
            )
        events = crh.recent_history()
        assert len(events) == 1
        assert events[0].fleet_revenue == 1500.0
        assert events[0].store_count == 3

    def test_negative_count_rejected(self, tmp_history):
        with self._w():
            ok = crh.record_snapshot(
                fleet_revenue=100.0, store_count=-1,
            )
        assert ok is False

    def test_window_filter(self, tmp_history):
        with self._w():
            crh.record_snapshot(
                fleet_revenue=100.0, store_count=1,
            )
        rows = json.loads(tmp_history.read_text())
        rows[0]["recorded_at"] = time.time() - 86400 * 60
        tmp_history.write_text(json.dumps(rows))
        assert crh.recent_history(
            since_seconds=86400 * 7,
        ) == []
        assert len(crh.recent_history(
            since_seconds=86400 * 90,
        )) == 1

    def test_cap_drops_oldest(self, tmp_history):
        with self._w():
            for i in range(1001):
                crh.record_snapshot(
                    fleet_revenue=float(i),
                    store_count=1,
                )
        raw = json.loads(tmp_history.read_text())
        assert len(raw) == 1000

    def test_corrupt_file_fails_open(self, tmp_history):
        tmp_history.write_text("not json{")
        assert crh.recent_history() == []


class TestRevenueTrend:

    def _w(self):
        return patch(
            "core.autonomous.cycle_revenue_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_empty(self, tmp_history):
        trend = crh.revenue_trend()
        assert trend["snapshots"] == 0
        assert trend["first_revenue"] is None
        assert trend["delta"] == 0.0

    def test_growth_computed(self, tmp_history):
        # Seed two snapshots directly
        first_ts = time.time() - 86400 * 5
        last_ts = time.time() - 60
        tmp_history.write_text(json.dumps([
            {
                "fleet_revenue": 1000.0,
                "store_count": 2,
                "recorded_at": first_ts,
            },
            {
                "fleet_revenue": 1500.0,
                "store_count": 2,
                "recorded_at": last_ts,
            },
        ]))
        trend = crh.revenue_trend()
        assert trend["snapshots"] == 2
        assert trend["first_revenue"] == 1000.0
        assert trend["last_revenue"] == 1500.0
        assert trend["delta"] == 500.0
        assert trend["delta_pct"] == 50.0

    def test_decline_computed(self, tmp_history):
        first_ts = time.time() - 86400 * 5
        last_ts = time.time() - 60
        tmp_history.write_text(json.dumps([
            {
                "fleet_revenue": 1000.0,
                "store_count": 2,
                "recorded_at": first_ts,
            },
            {
                "fleet_revenue": 800.0,
                "store_count": 2,
                "recorded_at": last_ts,
            },
        ]))
        trend = crh.revenue_trend()
        assert trend["delta"] == -200.0
        assert trend["delta_pct"] == -20.0


class TestClear:

    def test_under_pytest_no_op(self, tmp_history):
        tmp_history.write_text("[]")
        crh.clear()
        assert tmp_history.exists()

    def test_with_guard_off(self, tmp_history):
        tmp_history.write_text("[]")
        with patch(
            "core.autonomous.cycle_revenue_history."
            "_is_test_environment",
            return_value=False,
        ):
            crh.clear()
        assert not tmp_history.exists()
