"""Tests for ``core.capability_planner.auto_demote_history``.

Persistent audit log of bridge events. Coverage:

  - Pattern J guard short-circuits writes under pytest
  - Atomic write + fail-open read
  - Append + recent_history window filter
  - Thrashing detector (multiple demotes per capability)
  - Storage cap (1000 events)
  - Recorder hooks fire from auto_demote.maybe_*
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.capability_planner import (
    auto_demote,
    auto_demote_history as adh,
)


@pytest.fixture
def tmp_history(tmp_path):
    """Point the history file at a tmp path + lift Pattern J
    so write tests actually exercise the writer."""
    history_path = tmp_path / "auto_demote_history.json"
    adh._reset_for_tests(history_path)
    yield history_path
    # Reset back to module default for the next test
    adh._reset_for_tests(
        Path("data/auto_demote_history.json"),
    )


class TestPatternJ:

    def test_default_short_circuits(self, tmp_history):
        """Under pytest, record_* returns False + writes
        nothing."""
        ok = adh.record_demote("cap_x", "test reason")
        assert ok is False
        assert not tmp_history.exists()

    def test_disabled_guard_writes(self, tmp_history):
        with patch(
            "core.capability_planner."
            "auto_demote_history._is_test_environment",
            return_value=False,
        ):
            ok = adh.record_demote("cap_x", "test reason")
        assert ok is True
        assert tmp_history.exists()


class TestRecordAndRead:

    def test_demote_release_round_trip(self, tmp_history):
        with patch(
            "core.capability_planner."
            "auto_demote_history._is_test_environment",
            return_value=False,
        ):
            assert adh.record_demote(
                "cap_a", "auto_demote_degraded: ...",
            )
            assert adh.record_release(
                "cap_a", "auto_demote_release: ...",
            )
        events = adh.recent_history()
        assert len(events) == 2
        # newest-first
        assert events[0].kind == "release"
        assert events[1].kind == "demote"
        assert events[0].capability == "cap_a"

    def test_empty_capability_rejected(self, tmp_history):
        with patch(
            "core.capability_planner."
            "auto_demote_history._is_test_environment",
            return_value=False,
        ):
            assert adh.record_demote("", "x") is False
            assert adh.record_release("", "x") is False
        assert adh.recent_history() == []

    def test_window_filter(self, tmp_history):
        with patch(
            "core.capability_planner."
            "auto_demote_history._is_test_environment",
            return_value=False,
        ):
            adh.record_demote("cap_old", "")
        # Backfill timestamp to old
        rows = json.loads(tmp_history.read_text())
        rows[0]["recorded_at"] = time.time() - 86400 * 30
        tmp_history.write_text(json.dumps(rows))
        # 7-day window excludes 30-day-old event
        events = adh.recent_history(since_seconds=86400 * 7)
        assert events == []
        # 60-day window catches it
        events = adh.recent_history(
            since_seconds=86400 * 60,
        )
        assert len(events) == 1

    def test_storage_cap_drops_oldest(self, tmp_history):
        # Pre-populate with 1001 entries to force the cap
        with patch(
            "core.capability_planner."
            "auto_demote_history._is_test_environment",
            return_value=False,
        ):
            for i in range(1001):
                adh.record_demote(f"cap_{i}", "")
        # Each write reloads + caps; final file is at most
        # 1000 entries.
        raw = json.loads(tmp_history.read_text())
        assert len(raw) == 1000
        # Oldest entries (cap_0, cap_1) dropped; latest
        # entries kept.
        names = {e["capability"] for e in raw}
        assert "cap_1000" in names
        assert "cap_0" not in names

    def test_corrupt_file_fails_open(self, tmp_history):
        tmp_history.write_text("not json{")
        assert adh.recent_history() == []


class TestThrashing:

    def _seed_events(self, history_path, events):
        history_path.write_text(json.dumps(events))

    def test_no_thrashing_when_one_demote(
        self, tmp_history,
    ):
        now = time.time()
        self._seed_events(tmp_history, [{
            "kind": "demote", "capability": "cap_a",
            "reason": "", "recorded_at": now - 60,
        }])
        rows = adh.find_thrashing()
        assert rows == []

    def test_thrashing_detected_at_2_demotes(
        self, tmp_history,
    ):
        now = time.time()
        self._seed_events(tmp_history, [
            {
                "kind": "demote", "capability": "cap_a",
                "reason": "", "recorded_at": now - 86400 * 5,
            },
            {
                "kind": "release", "capability": "cap_a",
                "reason": "", "recorded_at": now - 86400 * 3,
            },
            {
                "kind": "demote", "capability": "cap_a",
                "reason": "", "recorded_at": now - 60,
            },
        ])
        rows = adh.find_thrashing()
        assert len(rows) == 1
        assert rows[0]["capability"] == "cap_a"
        assert rows[0]["demote_count"] == 2
        assert rows[0]["release_count"] == 1

    def test_thrashing_sorted_by_count(self, tmp_history):
        now = time.time()
        events = []
        # cap_a: 3 demotes
        for i in range(3):
            events.append({
                "kind": "demote", "capability": "cap_a",
                "reason": "",
                "recorded_at": now - 60 * (i + 1),
            })
        # cap_b: 2 demotes
        for i in range(2):
            events.append({
                "kind": "demote", "capability": "cap_b",
                "reason": "",
                "recorded_at": now - 60 * (i + 10),
            })
        self._seed_events(tmp_history, events)
        rows = adh.find_thrashing()
        assert [r["capability"] for r in rows] == [
            "cap_a", "cap_b",
        ]


class TestRecorderHooksFromAutoDemote:
    """When ``auto_demote.maybe_*`` writes via overrides,
    the history file should also receive an event."""

    @pytest.fixture(autouse=True)
    def _bridge_env(self, monkeypatch, tmp_history):
        monkeypatch.setenv(
            "SHOPAI_AUTO_DEMOTE_DEGRADED", "1",
        )
        yield

    def test_demote_call_records_event(self, tmp_history):
        degradations = [{
            "capability": "cap_x",
            "baseline_rate": 0.9, "recent_rate": 0.1,
            "drop": 0.8, "recent_samples": 5,
            "baseline_samples": 20,
        }]
        from core.capability_planner.\
capability_overrides import CapabilityOverrides
        with patch(
            "core.capability_planner.auto_demote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.auto_demote_history."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_degradations",
            return_value=degradations,
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=CapabilityOverrides(entries=[]),
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.demote",
            return_value=True,
        ):
            applied = (
                auto_demote.maybe_auto_demote_degraded()
            )
        assert len(applied) == 1
        # Event recorded
        events = adh.recent_history()
        assert len(events) == 1
        assert events[0].kind == "demote"
        assert events[0].capability == "cap_x"

    def test_release_call_records_event(self, tmp_history):
        from core.capability_planner.\
capability_overrides import (
            CapabilityOverride, CapabilityOverrides,
        )
        bridge_demote = CapabilityOverride(
            name="recovered",
            kind="demote",
            reason="auto_demote_degraded: ...",
            recorded_at=time.time() - 86400 * 10,
        )
        with patch(
            "core.capability_planner.auto_demote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner."
            "auto_demote_history._is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.load_overrides",
            return_value=CapabilityOverrides(
                entries=[bridge_demote],
            ),
        ), patch(
            "core.capability_planner.auto_demote."
            "plan_history.capability_leaderboard",
            return_value=[{
                "capability": "recovered",
                "executed_count": 5,
                "success_count": 5,
                "success_rate": 1.0,
            }],
        ), patch(
            "core.capability_planner.auto_demote."
            "capability_overrides.clear",
            return_value=True,
        ):
            released = (
                auto_demote.maybe_release_recovered()
            )
        assert len(released) == 1
        # Event recorded with the recovery rate in reason
        events = adh.recent_history()
        assert len(events) == 1
        assert events[0].kind == "release"
        assert events[0].capability == "recovered"
        assert "auto_demote_release" in events[0].reason


class TestClear:

    def test_clear_under_pytest_no_op(self, tmp_history):
        # Seed a file then call clear -- the Pattern J guard
        # short-circuits so the file remains.
        tmp_history.write_text("[]")
        adh.clear()
        assert tmp_history.exists()

    def test_clear_with_guard_off(self, tmp_history):
        tmp_history.write_text("[]")
        with patch(
            "core.capability_planner."
            "auto_demote_history._is_test_environment",
            return_value=False,
        ):
            adh.clear()
        assert not tmp_history.exists()
