"""Tests for ``core.autonomous.cycle_alert_history``.

Persistent log of cycle-alert firings. Coverage:

  - Pattern J guard short-circuits writes under pytest
  - Atomic write + fail-open read
  - record_alerts accepts both CycleAlert + dict shapes
  - recent_history window filter + newest-first ordering
  - consecutive_days_per_kind buckets by day
  - Storage cap
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import cycle_alert_history as cah
from core.autonomous.cycle_alerts import CycleAlert


@pytest.fixture
def tmp_history(tmp_path):
    history_path = tmp_path / "cycle_alert_history.json"
    cah._reset_for_tests(history_path)
    yield history_path
    cah._reset_for_tests(
        Path("data/cycle_alert_history.json"),
    )


class TestPatternJ:

    def test_default_short_circuits(self, tmp_history):
        ok = cah.record_alerts([
            CycleAlert(kind="stale_cycle", detail="x"),
        ])
        assert ok is False
        assert not tmp_history.exists()

    def test_disabled_guard_writes(self, tmp_history):
        with patch(
            "core.autonomous.cycle_alert_history."
            "_is_test_environment",
            return_value=False,
        ):
            ok = cah.record_alerts([
                CycleAlert(
                    kind="stale_cycle", detail="48h ago",
                ),
            ])
        assert ok is True
        assert tmp_history.exists()


class TestRecordAlerts:

    def _w(self):
        return patch(
            "core.autonomous.cycle_alert_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_round_trip_cyclealert(self, tmp_history):
        with self._w():
            cah.record_alerts([
                CycleAlert(
                    kind="low_advance_rate",
                    detail="20% rate",
                    metrics={
                        "advance_rate": 0.2,
                        "threshold": 0.5,
                    },
                ),
            ])
        events = cah.recent_history()
        assert len(events) == 1
        e = events[0]
        assert e.kind == "low_advance_rate"
        assert e.detail == "20% rate"
        assert e.metrics["advance_rate"] == 0.2

    def test_dict_form_accepted(self, tmp_history):
        with self._w():
            cah.record_alerts([
                {
                    "kind": "stale_cycle",
                    "detail": "stale",
                    "metrics": {"age_hours": 48},
                },
            ])
        events = cah.recent_history()
        assert len(events) == 1
        assert events[0].kind == "stale_cycle"

    def test_empty_kind_rejected(self, tmp_history):
        with self._w():
            cah.record_alerts([
                {"kind": "", "detail": "empty"},
                {"kind": "ok", "detail": "good"},
            ])
        events = cah.recent_history()
        assert len(events) == 1
        assert events[0].kind == "ok"

    def test_non_alert_skipped(self, tmp_history):
        with self._w():
            cah.record_alerts([
                "not-an-alert",
                None,
                42,
            ])
        events = cah.recent_history()
        assert events == []

    def test_empty_batch_returns_false(self, tmp_history):
        with self._w():
            ok = cah.record_alerts([])
        assert ok is False

    def test_window_filter(self, tmp_history):
        with self._w():
            cah.record_alerts([
                CycleAlert(
                    kind="stale_cycle", detail="x",
                ),
            ])
        rows = json.loads(tmp_history.read_text())
        rows[0]["recorded_at"] = time.time() - 86400 * 30
        tmp_history.write_text(json.dumps(rows))
        # 7-day window excludes
        assert cah.recent_history(
            since_seconds=86400 * 7,
        ) == []
        # 60-day window catches it
        events = cah.recent_history(
            since_seconds=86400 * 60,
        )
        assert len(events) == 1

    def test_cap_drops_oldest(self, tmp_history):
        with self._w():
            for i in range(1001):
                cah.record_alerts([{
                    "kind": f"k_{i}",
                    "detail": str(i),
                }])
        raw = json.loads(tmp_history.read_text())
        assert len(raw) == 1000

    def test_corrupt_file_fails_open(self, tmp_history):
        tmp_history.write_text("not json{")
        assert cah.recent_history() == []


class TestConsecutiveDays:

    def _seed(self, tmp_history, rows):
        tmp_history.write_text(json.dumps(rows))

    def test_no_history_empty(self, tmp_history):
        assert cah.consecutive_days_per_kind() == {}

    def test_single_kind_three_days(self, tmp_history):
        # Build 3 firings each in a different day-bucket
        now = time.time()
        self._seed(tmp_history, [
            {
                "kind": "stale_cycle",
                "detail": "",
                "recorded_at": now - 86400 * i,
                "metrics": {},
            }
            for i in range(3)
        ])
        counts = cah.consecutive_days_per_kind(
            window_seconds=86400 * 7, now=now,
        )
        assert counts == {"stale_cycle": 3}

    def test_same_bucket_counts_once(self, tmp_history):
        """3 firings within the same hour count as one
        bucket, not three."""
        now = time.time()
        self._seed(tmp_history, [
            {
                "kind": "stale_cycle",
                "detail": "",
                "recorded_at": now - 60 * i,
                "metrics": {},
            }
            for i in range(3)
        ])
        counts = cah.consecutive_days_per_kind(
            window_seconds=86400 * 7, now=now,
        )
        assert counts == {"stale_cycle": 1}

    def test_multiple_kinds_separated(self, tmp_history):
        now = time.time()
        self._seed(tmp_history, [
            {
                "kind": "stale_cycle", "detail": "",
                "recorded_at": now - 100, "metrics": {},
            },
            {
                "kind": "low_advance_rate", "detail": "",
                "recorded_at": now - 100, "metrics": {},
            },
            {
                "kind": "low_advance_rate", "detail": "",
                "recorded_at": now - 86400 - 100,
                "metrics": {},
            },
        ])
        counts = cah.consecutive_days_per_kind(
            window_seconds=86400 * 7, now=now,
        )
        assert counts == {
            "stale_cycle": 1,
            "low_advance_rate": 2,
        }

    def test_window_excludes_old(self, tmp_history):
        now = time.time()
        self._seed(tmp_history, [
            {
                "kind": "k", "detail": "",
                "recorded_at": now - 100, "metrics": {},
            },
            {
                "kind": "k", "detail": "",
                "recorded_at": now - 86400 * 30,
                "metrics": {},
            },
        ])
        counts = cah.consecutive_days_per_kind(
            window_seconds=86400 * 7, now=now,
        )
        assert counts == {"k": 1}


class TestClear:

    def test_under_pytest_no_op(self, tmp_history):
        tmp_history.write_text("[]")
        cah.clear()
        assert tmp_history.exists()

    def test_with_guard_off(self, tmp_history):
        tmp_history.write_text("[]")
        with patch(
            "core.autonomous.cycle_alert_history."
            "_is_test_environment",
            return_value=False,
        ):
            cah.clear()
        assert not tmp_history.exists()
