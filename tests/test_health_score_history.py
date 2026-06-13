"""Tests for ``core.autonomous.health_score_history``."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import health_score_history as hsh


@pytest.fixture
def tmp_history(tmp_path):
    path = tmp_path / "health_score_history.json"
    hsh._reset_for_tests(path)
    yield path
    hsh._reset_for_tests(
        Path("data/health_score_history.json"),
    )


class TestPatternJ:

    def test_default_short_circuits(self, tmp_history):
        ok = hsh.record_snapshot(score=80, verdict="ok")
        assert ok is False
        assert not tmp_history.exists()

    def test_disabled_guard_writes(self, tmp_history):
        with patch(
            "core.autonomous.health_score_history."
            "_is_test_environment",
            return_value=False,
        ):
            ok = hsh.record_snapshot(
                score=80, verdict="ok",
            )
        assert ok is True
        assert tmp_history.exists()


class TestRecord:

    def _w(self):
        return patch(
            "core.autonomous.health_score_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_round_trip(self, tmp_history):
        with self._w():
            hsh.record_snapshot(score=95, verdict="ok")
        events = hsh.recent_history()
        assert len(events) == 1
        assert events[0].score == 95
        assert events[0].verdict == "ok"

    def test_invalid_score_rejected(self, tmp_history):
        with self._w():
            assert (
                hsh.record_snapshot(
                    score=150, verdict="ok",
                ) is False
            )
            assert (
                hsh.record_snapshot(
                    score=-10, verdict="ok",
                ) is False
            )

    def test_invalid_verdict_rejected(self, tmp_history):
        with self._w():
            ok = hsh.record_snapshot(
                score=80, verdict="garbage",
            )
        assert ok is False

    def test_window_filter(self, tmp_history):
        with self._w():
            hsh.record_snapshot(score=80, verdict="ok")
        rows = json.loads(tmp_history.read_text())
        rows[0]["recorded_at"] = time.time() - 86400 * 30
        tmp_history.write_text(json.dumps(rows))
        assert hsh.recent_history(
            since_seconds=86400 * 7,
        ) == []
        assert len(hsh.recent_history(
            since_seconds=86400 * 90,
        )) == 1

    def test_cap_drops_oldest(self, tmp_history):
        with self._w():
            for i in range(1001):
                hsh.record_snapshot(
                    score=80, verdict="ok",
                )
        raw = json.loads(tmp_history.read_text())
        assert len(raw) == 1000

    def test_corrupt_file_fails_open(self, tmp_history):
        tmp_history.write_text("not json{")
        assert hsh.recent_history() == []


class TestScoreTrend:

    def _w(self):
        return patch(
            "core.autonomous.health_score_history."
            "_is_test_environment",
            return_value=False,
        )

    def test_empty_returns_zero(self, tmp_history):
        trend = hsh.score_trend()
        assert trend["snapshots"] == 0
        assert trend["delta"] == 0

    def test_growth_computed(self, tmp_history):
        first_ts = time.time() - 86400 * 3
        last_ts = time.time() - 60
        tmp_history.write_text(json.dumps([
            {
                "score": 70, "verdict": "warn",
                "recorded_at": first_ts,
            },
            {
                "score": 95, "verdict": "ok",
                "recorded_at": last_ts,
            },
        ]))
        trend = hsh.score_trend()
        assert trend["snapshots"] == 2
        assert trend["first_score"] == 70
        assert trend["last_score"] == 95
        assert trend["delta"] == 25
        assert trend["min_score"] == 70
        assert trend["max_score"] == 95

    def test_min_max_correct(self, tmp_history):
        now = time.time()
        tmp_history.write_text(json.dumps([
            {
                "score": 60, "verdict": "warn",
                "recorded_at": now - 86400 * 3,
            },
            {
                "score": 100, "verdict": "ok",
                "recorded_at": now - 86400 * 2,
            },
            {
                "score": 40, "verdict": "warn",
                "recorded_at": now - 86400,
            },
            {
                "score": 80, "verdict": "ok",
                "recorded_at": now - 60,
            },
        ]))
        trend = hsh.score_trend()
        assert trend["min_score"] == 40
        assert trend["max_score"] == 100
        assert trend["avg_score"] == 70.0


class TestClear:

    def test_under_pytest_no_op(self, tmp_history):
        tmp_history.write_text("[]")
        hsh.clear()
        assert tmp_history.exists()

    def test_with_guard_off(self, tmp_history):
        tmp_history.write_text("[]")
        with patch(
            "core.autonomous.health_score_history."
            "_is_test_environment",
            return_value=False,
        ):
            hsh.clear()
        assert not tmp_history.exists()
