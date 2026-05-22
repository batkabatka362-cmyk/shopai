"""Tests for ``core.autonomous.cycle_pause`` history tracking."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import cycle_pause as cp


@pytest.fixture
def tmp_paths(tmp_path):
    pause_path = tmp_path / "cycle_pause.json"
    hist_path = tmp_path / "cycle_pause_history.json"
    cp._reset_for_tests(pause_path, history_path=hist_path)
    yield pause_path, hist_path
    cp._reset_for_tests(
        Path("data/cycle_pause.json"),
        history_path=Path("data/cycle_pause_history.json"),
    )


def _disable_guard():
    return patch(
        "core.autonomous.cycle_pause."
        "_is_test_environment",
        return_value=False,
    )


class TestPatternJ:

    def test_default_short_circuits_history(self, tmp_paths):
        _, hist_path = tmp_paths
        # Under pytest, append should be a no-op
        cp._append_history_event(kind="pause")
        assert not hist_path.exists()

    def test_disabled_guard_writes(self, tmp_paths):
        _, hist_path = tmp_paths
        with _disable_guard():
            cp._append_history_event(
                kind="pause",
                reason="manual",
                paused_until_at=time.time() + 3600,
            )
        assert hist_path.exists()
        raw = json.loads(hist_path.read_text())
        assert len(raw) == 1
        assert raw[0]["kind"] == "pause"
        assert raw[0]["reason"] == "manual"


class TestPauseEmitsHistory:

    def test_pause_appends_event(self, tmp_paths):
        _, hist_path = tmp_paths
        until_at = time.time() + 7200
        with _disable_guard():
            ok = cp.pause(until_at=until_at, reason="maint")
        assert ok is True
        raw = json.loads(hist_path.read_text())
        assert len(raw) == 1
        assert raw[0]["kind"] == "pause"
        assert raw[0]["reason"] == "maint"
        assert raw[0]["paused_until_at"] == pytest.approx(
            until_at,
        )

    def test_extend_appends_event(self, tmp_paths):
        _, hist_path = tmp_paths
        until_at = time.time() + 3600
        with _disable_guard():
            cp.pause(until_at=until_at, reason="orig")
            ok = cp.extend(additional_hours=1.0)
        assert ok is True
        raw = json.loads(hist_path.read_text())
        kinds = [r["kind"] for r in raw]
        assert kinds == ["pause", "extend"]
        # extend's paused_until_at should be original + 3600
        assert raw[1]["paused_until_at"] == pytest.approx(
            until_at + 3600.0,
        )

    def test_resume_appends_event(self, tmp_paths):
        _, hist_path = tmp_paths
        until_at = time.time() + 1800
        with _disable_guard():
            cp.pause(until_at=until_at, reason="x")
            ok = cp.resume()
        assert ok is True
        raw = json.loads(hist_path.read_text())
        kinds = [r["kind"] for r in raw]
        assert kinds == ["pause", "resume"]


class TestPauseHistoryQuery:

    def test_empty_returns_empty(self, tmp_paths):
        assert cp.pause_history() == []

    def test_window_filter(self, tmp_paths):
        _, hist_path = tmp_paths
        now = time.time()
        hist_path.write_text(json.dumps([
            {
                "kind": "pause",
                "reason": "stale",
                "paused_until_at": now,
                "recorded_at": now - 86400 * 60,
            },
            {
                "kind": "resume",
                "reason": "",
                "paused_until_at": None,
                "recorded_at": now - 60,
            },
        ]))
        recent = cp.pause_history(
            since_seconds=86400 * 30,
        )
        assert len(recent) == 1
        assert recent[0]["kind"] == "resume"

    def test_newest_first(self, tmp_paths):
        _, hist_path = tmp_paths
        now = time.time()
        hist_path.write_text(json.dumps([
            {
                "kind": "pause",
                "reason": "first",
                "recorded_at": now - 600,
            },
            {
                "kind": "extend",
                "reason": "second",
                "recorded_at": now - 300,
            },
            {
                "kind": "resume",
                "reason": "third",
                "recorded_at": now - 60,
            },
        ]))
        events = cp.pause_history()
        assert [e["reason"] for e in events] == [
            "third", "second", "first",
        ]

    def test_cap_drops_oldest(self, tmp_paths):
        _, hist_path = tmp_paths
        with _disable_guard():
            for _ in range(1001):
                cp._append_history_event(kind="pause")
        raw = json.loads(hist_path.read_text())
        assert len(raw) == 1000

    def test_corrupt_file_fails_open(self, tmp_paths):
        _, hist_path = tmp_paths
        hist_path.write_text("not json{")
        assert cp.pause_history() == []


class TestClearHistory:

    def test_under_pytest_no_op(self, tmp_paths):
        _, hist_path = tmp_paths
        hist_path.write_text("[]")
        cp.clear_history()
        assert hist_path.exists()

    def test_with_guard_off(self, tmp_paths):
        _, hist_path = tmp_paths
        hist_path.write_text("[]")
        with _disable_guard():
            cp.clear_history()
        assert not hist_path.exists()
