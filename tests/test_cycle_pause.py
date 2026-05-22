"""Tests for ``core.autonomous.cycle_pause``."""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import cycle_pause as cp


@pytest.fixture
def tmp_pause(tmp_path):
    path = tmp_path / "cycle_pause.json"
    cp._reset_for_tests(path)
    yield path
    cp._reset_for_tests(Path("data/cycle_pause.json"))


class TestPatternJ:

    def test_pause_short_circuits(self, tmp_pause):
        ok = cp.pause(
            until_at=time.time() + 3600,
        )
        assert ok is False
        assert not tmp_pause.exists()

    def test_resume_short_circuits(self, tmp_pause):
        tmp_pause.write_text(json.dumps({
            "paused_until_at": time.time() + 3600,
        }))
        ok = cp.resume()
        assert ok is False
        # File still exists
        assert tmp_pause.exists()

    def test_with_guard_off_writes(self, tmp_pause):
        with patch(
            "core.autonomous.cycle_pause."
            "_is_test_environment",
            return_value=False,
        ):
            ok = cp.pause(
                until_at=time.time() + 3600,
                reason="test",
            )
        assert ok is True
        assert tmp_pause.exists()


class TestPauseState:

    def test_not_paused_default(self, tmp_pause):
        assert cp.is_paused() is False
        state = cp.get_pause_state()
        assert state["active"] is False

    def test_active_pause_reflected(self, tmp_pause):
        # Seed via direct write
        tmp_pause.write_text(json.dumps({
            "paused_until_at": time.time() + 3600,
            "reason": "maintenance",
            "paused_at": time.time(),
        }))
        state = cp.get_pause_state()
        assert state["active"] is True
        assert state["reason"] == "maintenance"
        assert cp.is_paused() is True

    def test_expired_pause_inactive(self, tmp_pause):
        tmp_pause.write_text(json.dumps({
            "paused_until_at": time.time() - 60,
            "reason": "stale",
        }))
        assert cp.is_paused() is False

    def test_corrupt_file_inactive(self, tmp_pause):
        tmp_pause.write_text("not json{")
        assert cp.is_paused() is False


class TestResume:

    def test_resume_removes_file(self, tmp_pause):
        tmp_pause.write_text("{}")
        with patch(
            "core.autonomous.cycle_pause."
            "_is_test_environment",
            return_value=False,
        ):
            ok = cp.resume()
        assert ok is True
        assert not tmp_pause.exists()

    def test_resume_missing_returns_false(
        self, tmp_pause,
    ):
        with patch(
            "core.autonomous.cycle_pause."
            "_is_test_environment",
            return_value=False,
        ):
            ok = cp.resume()
        assert ok is False


class TestInvalidArgs:

    def test_negative_until_rejected(self, tmp_pause):
        with patch(
            "core.autonomous.cycle_pause."
            "_is_test_environment",
            return_value=False,
        ):
            ok = cp.pause(until_at=-1)
        assert ok is False

    def test_zero_until_rejected(self, tmp_pause):
        with patch(
            "core.autonomous.cycle_pause."
            "_is_test_environment",
            return_value=False,
        ):
            ok = cp.pause(until_at=0)
        assert ok is False


class TestClear:

    def test_under_pytest_no_op(self, tmp_pause):
        tmp_pause.write_text("{}")
        cp.clear()
        assert tmp_pause.exists()

    def test_with_guard_off(self, tmp_pause):
        tmp_pause.write_text("{}")
        with patch(
            "core.autonomous.cycle_pause."
            "_is_test_environment",
            return_value=False,
        ):
            cp.clear()
        assert not tmp_pause.exists()
