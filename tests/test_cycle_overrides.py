"""Tests for ``core.autonomous.cycle_overrides``.

Layered threshold lookup: persistent file > env var >
default. Operator writes survive restarts.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from core.autonomous import cycle_overrides as co


@pytest.fixture
def tmp_overrides(tmp_path):
    path = tmp_path / "cycle_overrides.json"
    co._reset_for_tests(path)
    yield path
    co._reset_for_tests(
        Path("data/cycle_overrides.json"),
    )


@pytest.fixture(autouse=True)
def _clean_env():
    """Strip the env vars between tests so layered lookup
    is exercised cleanly."""
    saved = {
        k: os.environ.pop(k, None)
        for k in (
            "SHOPAI_AUTO_EXECUTE_THRESHOLD",
            "SHOPAI_AUTO_EXECUTE_MIN_SAMPLE",
        )
    }
    yield
    for k in (
        "SHOPAI_AUTO_EXECUTE_THRESHOLD",
        "SHOPAI_AUTO_EXECUTE_MIN_SAMPLE",
    ):
        os.environ.pop(k, None)
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


class TestPatternJ:

    def test_set_short_circuits(self, tmp_overrides):
        ok = co.set_override("auto_execute_threshold", 0.8)
        assert ok is False
        assert not tmp_overrides.exists()

    def test_clear_short_circuits(self, tmp_overrides):
        tmp_overrides.write_text(
            json.dumps({
                "auto_execute_threshold": 0.7,
            }),
        )
        ok = co.clear_override(
            "auto_execute_threshold",
        )
        assert ok is False
        # File still exists
        assert tmp_overrides.exists()

    def test_with_guard_off_writes(self, tmp_overrides):
        with patch(
            "core.autonomous.cycle_overrides."
            "_is_test_environment",
            return_value=False,
        ):
            ok = co.set_override(
                "auto_execute_threshold", 0.7,
            )
        assert ok is True
        assert tmp_overrides.exists()


class TestSetClear:

    def _w(self):
        return patch(
            "core.autonomous.cycle_overrides."
            "_is_test_environment",
            return_value=False,
        )

    def test_round_trip(self, tmp_overrides):
        with self._w():
            co.set_override(
                "auto_execute_threshold", 0.65,
            )
        data = co.load_overrides()
        assert data["auto_execute_threshold"] == 0.65

    def test_unknown_key_rejected(self, tmp_overrides):
        with self._w():
            ok = co.set_override("ghost_key", "x")
        assert ok is False
        assert not tmp_overrides.exists()

    def test_invalid_value_rejected(self, tmp_overrides):
        with self._w():
            ok = co.set_override(
                "auto_execute_threshold", "not-a-number",
            )
        assert ok is False

    def test_clear_removes_key(self, tmp_overrides):
        with self._w():
            co.set_override(
                "auto_execute_threshold", 0.65,
            )
            co.set_override(
                "auto_execute_min_sample", 3,
            )
            ok = co.clear_override(
                "auto_execute_threshold",
            )
        assert ok is True
        data = co.load_overrides()
        assert "auto_execute_threshold" not in data
        assert "auto_execute_min_sample" in data

    def test_clear_missing_returns_false(
        self, tmp_overrides,
    ):
        with self._w():
            ok = co.clear_override(
                "auto_execute_threshold",
            )
        assert ok is False

    def test_clear_all(self, tmp_overrides):
        tmp_overrides.write_text(
            json.dumps({"k": "v"}),
        )
        with self._w():
            co.clear_all()
        assert not tmp_overrides.exists()

    def test_corrupt_file_fails_open(
        self, tmp_overrides,
    ):
        tmp_overrides.write_text("not json{")
        assert co.load_overrides() == {}


class TestLayeredResolve:

    def _w(self):
        return patch(
            "core.autonomous.cycle_overrides."
            "_is_test_environment",
            return_value=False,
        )

    def test_default_when_nothing_set(
        self, tmp_overrides,
    ):
        assert co.resolve_threshold() == 0.9
        assert co.resolve_min_sample() == 5

    def test_env_overrides_default(self, tmp_overrides):
        os.environ["SHOPAI_AUTO_EXECUTE_THRESHOLD"] = "0.7"
        os.environ["SHOPAI_AUTO_EXECUTE_MIN_SAMPLE"] = "3"
        assert co.resolve_threshold() == 0.7
        assert co.resolve_min_sample() == 3

    def test_file_overrides_env(self, tmp_overrides):
        os.environ["SHOPAI_AUTO_EXECUTE_THRESHOLD"] = "0.7"
        with self._w():
            co.set_override(
                "auto_execute_threshold", 0.55,
            )
        # File wins
        assert co.resolve_threshold() == 0.55

    def test_invalid_file_value_falls_through(
        self, tmp_overrides,
    ):
        # Hand-write an invalid value
        tmp_overrides.write_text(
            json.dumps({
                "auto_execute_threshold": "abc",
            }),
        )
        os.environ["SHOPAI_AUTO_EXECUTE_THRESHOLD"] = "0.6"
        # Falls through to env
        assert co.resolve_threshold() == 0.6

    def test_clear_restores_env(self, tmp_overrides):
        os.environ["SHOPAI_AUTO_EXECUTE_THRESHOLD"] = "0.65"
        with self._w():
            co.set_override(
                "auto_execute_threshold", 0.5,
            )
            assert co.resolve_threshold() == 0.5
            co.clear_override("auto_execute_threshold")
        # Env takes over again
        assert co.resolve_threshold() == 0.65


class TestControllerIntegration:
    """The autonomous controller's
    _compute_auto_execute_eligibility now consults the
    layered resolver."""

    def _w(self):
        return patch(
            "core.autonomous.cycle_overrides."
            "_is_test_environment",
            return_value=False,
        )

    def test_threshold_flows_into_eligibility(
        self, tmp_overrides,
    ):
        from core.autonomous.controller import (
            _compute_auto_execute_eligibility,
        )

        class _FakeStep:
            history_sample_size = 10
            history_success_rate = 0.6
            capability_name = "cap_a"

        class _FakePlan:
            steps = [_FakeStep()]

        # With default 0.9 threshold, this step is NOT
        # eligible (0.6 < 0.9).
        info = _compute_auto_execute_eligibility(
            _FakePlan(),
        )
        assert info["threshold"] == 0.9
        assert info["eligible_count"] == 0

        # Lower the threshold via override -> now eligible.
        with self._w():
            co.set_override(
                "auto_execute_threshold", 0.5,
            )
        info = _compute_auto_execute_eligibility(
            _FakePlan(),
        )
        assert info["threshold"] == 0.5
        assert info["eligible_count"] == 1
