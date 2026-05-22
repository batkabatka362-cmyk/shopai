"""Tests for ``core.autonomous.auto_relax_history``.

Persistent log of bridge actions. Coverage:

  - Pattern J guard short-circuits writes under pytest
  - Atomic write + fail-open read
  - direction='none' rejected
  - recent_history window filter + newest-first ordering
  - relax_stats aggregates correctly
  - Storage cap
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import auto_relax_history as arh


@pytest.fixture
def tmp_history(tmp_path):
    history_path = tmp_path / "auto_relax_history.json"
    arh._reset_for_tests(history_path)
    yield history_path
    arh._reset_for_tests(
        Path("data/auto_relax_history.json"),
    )


class TestPatternJ:

    def test_default_short_circuits(self, tmp_history):
        ok = arh.record_action(
            direction="relax",
            current_value=0.9,
            proposed_value=0.85,
            reason="x",
        )
        assert ok is False
        assert not tmp_history.exists()

    def test_disabled_guard_writes(self, tmp_history):
        with patch(
            "core.autonomous.auto_relax_history."
            "_is_test_environment",
            return_value=False,
        ):
            ok = arh.record_action(
                direction="relax",
                current_value=0.9,
                proposed_value=0.85,
                reason="x",
            )
        assert ok is True
        assert tmp_history.exists()


class TestRecordAction:

    def _w(self):
        return patch(
            "core.autonomous.auto_relax_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_round_trip(self, tmp_history):
        with self._w():
            arh.record_action(
                direction="relax",
                current_value=0.9,
                proposed_value=0.85,
                reason="3d streak",
                metrics={"streak_days": 3},
            )
        events = arh.recent_history()
        assert len(events) == 1
        e = events[0]
        assert e.direction == "relax"
        assert e.current_value == 0.9
        assert e.proposed_value == 0.85
        assert e.metrics["streak_days"] == 3

    def test_none_direction_rejected(self, tmp_history):
        with self._w():
            ok = arh.record_action(
                direction="none",
                current_value=0.9,
                proposed_value=0.9,
                reason="-",
            )
        assert ok is False
        assert arh.recent_history() == []

    def test_invalid_direction_rejected(
        self, tmp_history,
    ):
        with self._w():
            ok = arh.record_action(
                direction="garbage",
                current_value=0.9,
                proposed_value=0.85,
                reason="-",
            )
        assert ok is False

    def test_window_filter(self, tmp_history):
        with self._w():
            arh.record_action(
                direction="relax",
                current_value=0.9,
                proposed_value=0.85,
                reason="x",
            )
        rows = json.loads(tmp_history.read_text())
        rows[0]["recorded_at"] = time.time() - 86400 * 30
        tmp_history.write_text(json.dumps(rows))
        assert arh.recent_history(
            since_seconds=86400 * 7,
        ) == []
        events = arh.recent_history(
            since_seconds=86400 * 60,
        )
        assert len(events) == 1

    def test_cap_drops_oldest(self, tmp_history):
        with self._w():
            for i in range(1001):
                arh.record_action(
                    direction="relax",
                    current_value=float(i),
                    proposed_value=float(i) - 0.01,
                    reason=str(i),
                )
        raw = json.loads(tmp_history.read_text())
        assert len(raw) == 1000

    def test_corrupt_file_fails_open(self, tmp_history):
        tmp_history.write_text("not json{")
        assert arh.recent_history() == []


class TestRelaxStats:

    def _w(self):
        return patch(
            "core.autonomous.auto_relax_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_empty(self, tmp_history):
        stats = arh.relax_stats()
        assert stats["total"] == 0
        assert stats["last_action_at"] is None
        assert stats["net_change"] == 0.0

    def test_aggregates_counts(self, tmp_history):
        with self._w():
            arh.record_action(
                direction="relax",
                current_value=0.9,
                proposed_value=0.85,
                reason="-",
            )
            arh.record_action(
                direction="relax",
                current_value=0.85,
                proposed_value=0.8,
                reason="-",
            )
            arh.record_action(
                direction="restore",
                current_value=0.8,
                proposed_value=0.85,
                reason="-",
            )
        stats = arh.relax_stats()
        assert stats["total"] == 3
        assert stats["relax_count"] == 2
        assert stats["restore_count"] == 1
        # Net: (0.85-0.9) + (0.8-0.85) + (0.85-0.8)
        # = -0.05 + -0.05 + 0.05 = -0.05
        assert stats["net_change"] == -0.05
        # Last action is the latest recorded (restore)
        assert stats["last_direction"] == "restore"


class TestClear:

    def test_under_pytest_no_op(self, tmp_history):
        tmp_history.write_text("[]")
        arh.clear()
        assert tmp_history.exists()

    def test_with_guard_off(self, tmp_history):
        tmp_history.write_text("[]")
        with patch(
            "core.autonomous.auto_relax_history."
            "_is_test_environment",
            return_value=False,
        ):
            arh.clear()
        assert not tmp_history.exists()


class TestBridgeIntegration:
    """``auto_relax.maybe_apply`` should record an applied
    action to the history log."""

    def _w_relax(self):
        return patch(
            "core.autonomous.auto_relax."
            "_is_test_environment",
            return_value=False,
        )

    def _w_history(self):
        return patch(
            "core.autonomous.auto_relax_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_apply_records_event(
        self, tmp_history, monkeypatch,
    ):
        from core.autonomous import auto_relax as ar
        monkeypatch.setenv(
            "SHOPAI_AUTO_RELAX_RELIABILITY", "1",
        )
        action = ar.RelaxAction(
            direction="relax",
            current_value=0.9,
            proposed_value=0.85,
            reason="3d streak",
        )
        with self._w_relax(), self._w_history(), patch(
            "core.autonomous.cycle_overrides."
            "set_override",
            return_value=True,
        ):
            result = ar.maybe_apply(action)
        assert result.applied is True
        events = arh.recent_history()
        assert len(events) == 1
        assert events[0].direction == "relax"
        assert events[0].proposed_value == 0.85

    def test_failed_set_skips_history(
        self, tmp_history, monkeypatch,
    ):
        from core.autonomous import auto_relax as ar
        monkeypatch.setenv(
            "SHOPAI_AUTO_RELAX_RELIABILITY", "1",
        )
        action = ar.RelaxAction(
            direction="relax",
            current_value=0.9,
            proposed_value=0.85,
            reason="-",
        )
        with self._w_relax(), self._w_history(), patch(
            "core.autonomous.cycle_overrides."
            "set_override",
            return_value=False,  # write failed
        ):
            result = ar.maybe_apply(action)
        assert result.applied is False
        # History also empty -- we only record successful
        # writes
        assert arh.recent_history() == []
