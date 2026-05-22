"""Tests for ``core.autonomous.cycle_history``.

Persistent log of ``shopai autonomous-cycle`` invocations.
Coverage:

  - Pattern J guard short-circuits writes
  - Atomic write + fail-open read
  - cycle_stats aggregates correctly
  - Storage cap
  - 1000-event cap
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import cycle_history as ch


@pytest.fixture
def tmp_history(tmp_path):
    history_path = tmp_path / "cycle_history.json"
    ch._reset_for_tests(history_path)
    yield history_path
    ch._reset_for_tests(Path("data/cycle_history.json"))


class TestPatternJ:

    def test_default_short_circuits(self, tmp_history):
        ok = ch.record_cycle(executed=True)
        assert ok is False
        assert not tmp_history.exists()

    def test_disabled_guard_writes(self, tmp_history):
        with patch(
            "core.autonomous.cycle_history."
            "_is_test_environment",
            return_value=False,
        ):
            ok = ch.record_cycle(executed=True)
        assert ok is True
        assert tmp_history.exists()


class TestRecordAndRead:

    def _w(self):
        return patch(
            "core.autonomous.cycle_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_round_trip(self, tmp_history):
        with self._w():
            ch.record_cycle(
                executed=True,
                advance={
                    "stores_processed": 2,
                    "executed_ok": 1,
                    "refused_reliability": 1,
                    "errored": 0,
                },
                defend={"demoted": 1, "released": 0},
                correlate={"correlated": 3},
                flags={"skip_advance": False},
            )
        events = ch.recent_history()
        assert len(events) == 1
        e = events[0]
        assert e.executed is True
        assert e.advance["executed_ok"] == 1
        assert e.defend["demoted"] == 1
        assert e.correlate["correlated"] == 3
        assert e.flags["skip_advance"] is False

    def test_window_filter(self, tmp_history):
        with self._w():
            ch.record_cycle(executed=True)
        rows = json.loads(tmp_history.read_text())
        rows[0]["recorded_at"] = time.time() - 86400 * 30
        tmp_history.write_text(json.dumps(rows))
        # 7-day window excludes
        assert ch.recent_history(since_seconds=86400 * 7) == []
        # 60-day window catches it
        events = ch.recent_history(
            since_seconds=86400 * 60,
        )
        assert len(events) == 1

    def test_cap_drops_oldest(self, tmp_history):
        with self._w():
            for i in range(1001):
                ch.record_cycle(executed=i % 2 == 0)
        raw = json.loads(tmp_history.read_text())
        assert len(raw) == 1000

    def test_corrupt_file_fails_open(self, tmp_history):
        tmp_history.write_text("not json{")
        assert ch.recent_history() == []


class TestCycleStats:

    def _w(self):
        return patch(
            "core.autonomous.cycle_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_empty_returns_zero_stats(self, tmp_history):
        stats = ch.cycle_stats()
        assert stats["total_runs"] == 0
        assert stats["last_run_at"] is None

    def test_aggregates_across_events(self, tmp_history):
        with self._w():
            ch.record_cycle(
                executed=True,
                advance={
                    "executed_ok": 2,
                    "refused_reliability": 1,
                },
                defend={"demoted": 1, "released": 0},
                correlate={"correlated": 2},
            )
            ch.record_cycle(
                executed=True,
                advance={
                    "executed_ok": 1,
                    "refused_reliability": 0,
                },
                defend={"demoted": 0, "released": 2},
                correlate={"correlated": 1},
            )
            ch.record_cycle(executed=False)  # dry-run
        stats = ch.cycle_stats()
        assert stats["total_runs"] == 3
        assert stats["executed_runs"] == 2
        assert stats["dry_run_count"] == 1
        assert stats["stores_advanced_total"] == 3  # 2 + 1
        assert stats["stores_refused_total"] == 1
        assert stats["demoted_total"] == 1
        assert stats["released_total"] == 2
        assert stats["correlated_total"] == 3

    def test_last_run_at_newest(self, tmp_history):
        with self._w():
            ch.record_cycle(executed=True)
            ch.record_cycle(executed=True)
        stats = ch.cycle_stats()
        # Reading: newest comes first
        events = ch.recent_history()
        assert stats["last_run_at"] == events[0].recorded_at


class TestClear:

    def test_clear_under_pytest_no_op(self, tmp_history):
        tmp_history.write_text("[]")
        ch.clear()
        assert tmp_history.exists()

    def test_clear_with_guard_off(self, tmp_history):
        tmp_history.write_text("[]")
        with patch(
            "core.autonomous.cycle_history."
            "_is_test_environment",
            return_value=False,
        ):
            ch.clear()
        assert not tmp_history.exists()
