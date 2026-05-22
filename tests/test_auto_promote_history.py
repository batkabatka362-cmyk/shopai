"""Tests for ``core.capability_planner.auto_promote_history``."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.capability_planner import auto_promote_history as aph


@pytest.fixture
def tmp_history(tmp_path):
    history_path = tmp_path / "auto_promote_history.json"
    aph._reset_for_tests(history_path)
    yield history_path
    aph._reset_for_tests(
        Path("data/auto_promote_history.json"),
    )


class TestPatternJ:

    def test_default_short_circuits(self, tmp_history):
        ok = aph.record_promote(
            capability="cap_a",
            reason="winner",
        )
        assert ok is False
        assert not tmp_history.exists()

    def test_disabled_guard_writes(self, tmp_history):
        with patch(
            "core.capability_planner."
            "auto_promote_history._is_test_environment",
            return_value=False,
        ):
            ok = aph.record_promote(
                capability="cap_a",
                reason="winner",
            )
        assert ok is True
        assert tmp_history.exists()


class TestRecordPromote:

    def _w(self):
        return patch(
            "core.capability_planner."
            "auto_promote_history._is_test_environment",
            return_value=False,
        )

    def test_round_trip(self, tmp_history):
        with self._w():
            aph.record_promote(
                capability="winner",
                reason="auto_promote: rate=1.0",
                metrics={"success_rate": 1.0},
            )
        events = aph.recent_history()
        assert len(events) == 1
        assert events[0].capability == "winner"
        assert events[0].metrics["success_rate"] == 1.0

    def test_empty_capability_rejected(
        self, tmp_history,
    ):
        with self._w():
            ok = aph.record_promote(
                capability="",
                reason="x",
            )
        assert ok is False

    def test_capability_filter(self, tmp_history):
        with self._w():
            aph.record_promote(
                capability="cap_a",
                reason="r",
            )
            aph.record_promote(
                capability="cap_b",
                reason="r",
            )
        events = aph.recent_history(capability="cap_a")
        assert len(events) == 1
        assert events[0].capability == "cap_a"

    def test_window_filter(self, tmp_history):
        with self._w():
            aph.record_promote(
                capability="cap_a",
                reason="r",
            )
        rows = json.loads(tmp_history.read_text())
        rows[0]["recorded_at"] = time.time() - 86400 * 30
        tmp_history.write_text(json.dumps(rows))
        assert aph.recent_history(
            since_seconds=86400 * 7,
        ) == []
        assert len(
            aph.recent_history(since_seconds=86400 * 60),
        ) == 1

    def test_cap_drops_oldest(self, tmp_history):
        with self._w():
            for i in range(1001):
                aph.record_promote(
                    capability=f"cap_{i}",
                    reason="r",
                )
        raw = json.loads(tmp_history.read_text())
        assert len(raw) == 1000

    def test_corrupt_file_fails_open(self, tmp_history):
        tmp_history.write_text("not json{")
        assert aph.recent_history() == []


class TestPromoteStats:

    def _w(self):
        return patch(
            "core.capability_planner."
            "auto_promote_history._is_test_environment",
            return_value=False,
        )

    def test_empty(self, tmp_history):
        stats = aph.promote_stats()
        assert stats["total"] == 0
        assert stats["by_capability"] == {}
        assert stats["last_promote_at"] is None

    def test_aggregates(self, tmp_history):
        with self._w():
            aph.record_promote(
                capability="cap_a", reason="r",
            )
            aph.record_promote(
                capability="cap_a", reason="r",
            )
            aph.record_promote(
                capability="cap_b", reason="r",
            )
        stats = aph.promote_stats()
        assert stats["total"] == 3
        assert stats["by_capability"]["cap_a"] == 2
        assert stats["by_capability"]["cap_b"] == 1


class TestClear:

    def test_under_pytest_no_op(self, tmp_history):
        tmp_history.write_text("[]")
        aph.clear()
        assert tmp_history.exists()

    def test_with_guard_off(self, tmp_history):
        tmp_history.write_text("[]")
        with patch(
            "core.capability_planner."
            "auto_promote_history._is_test_environment",
            return_value=False,
        ):
            aph.clear()
        assert not tmp_history.exists()


class TestBridgeIntegration:
    """auto_promote.maybe_auto_promote_reliable should
    record applied promotes to the history."""

    def test_apply_records_event(
        self, tmp_history, monkeypatch,
    ):
        from core.capability_planner import (
            auto_promote as ap,
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_PROMOTE_RELIABLE", "1",
        )
        rows = [{
            "capability": "winner",
            "executed_count": 10,
            "success_count": 10,
            "success_rate": 1.0,
        }]
        from core.capability_planner.\
capability_overrides import CapabilityOverrides
        with patch(
            "core.capability_planner.auto_promote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner."
            "auto_promote_history._is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=CapabilityOverrides(entries=[]),
        ), patch(
            "core.capability_planner.capability_overrides."
            "promote",
            return_value=True,
        ):
            applied = ap.maybe_auto_promote_reliable()
        assert len(applied) == 1
        events = aph.recent_history()
        assert len(events) == 1
        assert events[0].capability == "winner"
