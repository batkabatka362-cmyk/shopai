"""Tests for the generic autonomy substrate (Wave 117-119).

These exercise ``core/automation/{action_log,pause_state,
health_analyzer}.py`` -- the extracted pattern shared by
refund_log/refund_state/refund_health and ad_spend_log/
budget_state/budget_health.

Future autonomous loops (fulfillment, customer outreach,
inventory restocking) can adopt this substrate without
re-implementing the boilerplate.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

from core.automation.action_log import (
    is_test_environment,
    load_log,
    log_size,
    record_event,
    recent_events,
    save_log,
)
from core.automation.health_analyzer import (
    HealthReport,
    analyze_health,
    maybe_auto_pause,
)
from core.automation.pause_state import (
    PauseState,
    get_state,
    is_paused,
    load_state,
    pause,
    resume,
    save_state,
)


# Synthetic dataclass mimicking a domain log entry
@dataclass
class FakeEvent:
    action_id: str
    store_id: str = ""
    applied: bool = False
    status: str = ""
    recorded_at: float = 0.0


# ─── action_log ──────────────────────────────────────────


class TestActionLog:

    def test_pattern_j_guard_blocks_writes(self, tmp_path):
        """record_event no-ops under PYTEST_CURRENT_TEST."""
        path = tmp_path / "log.json"
        record_event(path, FakeEvent(
            action_id="a1", applied=True, status="ok",
        ))
        # Pattern J: nothing persisted
        assert not path.exists()

    def test_save_load_round_trip(self, tmp_path):
        path = tmp_path / "log.json"
        rows = [
            {"action_id": "a1", "recorded_at": time.time()},
            {"action_id": "a2", "recorded_at": time.time()},
        ]
        # Bypass the test guard via direct save
        with patch(
            "core.automation.action_log.is_test_environment",
            return_value=False,
        ):
            save_log(path, rows)
        loaded = load_log(path)
        assert len(loaded) == 2
        assert loaded[0]["action_id"] == "a1"

    def test_save_bounded_to_max_entries(self, tmp_path):
        path = tmp_path / "log.json"
        rows = [
            {"action_id": f"a{i}", "recorded_at": time.time()}
            for i in range(20)
        ]
        with patch(
            "core.automation.action_log.is_test_environment",
            return_value=False,
        ):
            save_log(path, rows, max_entries=5)
        loaded = load_log(path)
        # Only the last 5 entries survive
        assert len(loaded) == 5
        assert loaded[0]["action_id"] == "a15"

    def test_record_event_auto_populates_recorded_at(
        self, tmp_path,
    ):
        path = tmp_path / "log.json"
        with patch(
            "core.automation.action_log.is_test_environment",
            return_value=False,
        ):
            record_event(path, FakeEvent(
                action_id="a1", applied=True, status="ok",
                # recorded_at defaults to 0
            ))
        loaded = load_log(path)
        # auto-populated
        assert loaded[0]["recorded_at"] > 0

    def test_record_non_dataclass_ignored(self, tmp_path):
        path = tmp_path / "log.json"
        with patch(
            "core.automation.action_log.is_test_environment",
            return_value=False,
        ):
            record_event(path, "not_a_dataclass")
        assert not path.exists()

    def test_recent_events_filters_by_window(self, tmp_path):
        path = tmp_path / "log.json"
        now = time.time()
        rows = [
            {"action_id": "old", "recorded_at": now - 36000},
            {"action_id": "new", "recorded_at": now - 60},
        ]
        with patch(
            "core.automation.action_log.is_test_environment",
            return_value=False,
        ):
            save_log(path, rows)
        out = recent_events(path, window_hours=1.0)
        assert len(out) == 1
        assert out[0]["action_id"] == "new"

    def test_recent_events_filters_by_arbitrary_keys(
        self, tmp_path,
    ):
        path = tmp_path / "log.json"
        now = time.time()
        rows = [
            {
                "action_id": "a1", "store_id": "store_a",
                "recorded_at": now,
            },
            {
                "action_id": "a2", "store_id": "store_b",
                "recorded_at": now,
            },
        ]
        with patch(
            "core.automation.action_log.is_test_environment",
            return_value=False,
        ):
            save_log(path, rows)
        out = recent_events(
            path, filters={"store_id": "store_a"},
        )
        assert len(out) == 1
        assert out[0]["action_id"] == "a1"

    def test_recent_events_sorts_newest_first(self, tmp_path):
        path = tmp_path / "log.json"
        now = time.time()
        rows = [
            {"action_id": "old", "recorded_at": now - 3600},
            {"action_id": "new", "recorded_at": now - 60},
        ]
        with patch(
            "core.automation.action_log.is_test_environment",
            return_value=False,
        ):
            save_log(path, rows)
        out = recent_events(path, window_hours=24.0)
        assert out[0]["action_id"] == "new"


# ─── pause_state ─────────────────────────────────────────


class TestPauseState:

    def test_default_state_unpaused(self, tmp_path):
        path = tmp_path / "state.json"
        state = load_state(path)
        assert state.paused is False
        assert state.reason == ""

    def test_pause_then_resume(self, tmp_path):
        path = tmp_path / "state.json"
        with patch(
            "core.automation.pause_state.is_test_environment",
            return_value=False,
        ):
            state = pause(path, reason="test")
            assert state.paused is True
            assert is_paused(path) is True
            state2 = resume(path)
            assert state2.paused is False
            assert is_paused(path) is False

    def test_auto_resume_after_deadline(self, tmp_path):
        path = tmp_path / "state.json"
        with patch(
            "core.automation.pause_state.is_test_environment",
            return_value=False,
        ):
            pause(
                path,
                reason="test",
                auto_resume_after=time.time() - 60,
            )
            state = get_state(path)
            assert state.paused is False

    def test_save_state_pattern_j(self, tmp_path):
        """save_state no-ops under PYTEST_CURRENT_TEST."""
        path = tmp_path / "state.json"
        save_state(path, PauseState(paused=True))
        # Pattern J: not persisted
        assert not path.exists()


# ─── health_analyzer ─────────────────────────────────────


def _fake_events(failure_count: int, success_count: int = 0):
    """Build synthetic event rows with given failure ratio."""
    return (
        [
            {
                "applied": True, "status": "recorded",
                "recorded_at": time.time(),
            }
            for _ in range(success_count)
        ]
        + [
            {
                "applied": False, "status": "adapter_failed",
                "recorded_at": time.time(),
            }
            for _ in range(failure_count)
        ]
    )


class TestHealthAnalyzer:

    def test_small_sample_returns_healthy(self):
        """Below min_sample -> healthy regardless of ratio."""
        report = analyze_health(
            env_prefix="TEST_DOMAIN",
            window_hours=24.0,
            recent_events_fn=(
                lambda **kw: _fake_events(failure_count=2)
            ),
            is_paused_fn=lambda: False,
        )
        assert report.verdict == "healthy"
        assert "insufficient data" in report.reasons[0]

    def test_high_failure_critical(self):
        report = analyze_health(
            env_prefix="TEST_DOMAIN",
            window_hours=24.0,
            recent_events_fn=(
                lambda **kw: _fake_events(failure_count=8)
            ),
            is_paused_fn=lambda: False,
        )
        assert report.verdict == "critical"
        assert report.failure_ratio == 1.0

    def test_already_paused_field(self):
        report = analyze_health(
            env_prefix="TEST_DOMAIN",
            window_hours=24.0,
            recent_events_fn=(
                lambda **kw: _fake_events(failure_count=8)
            ),
            is_paused_fn=lambda: True,
        )
        assert report.already_paused is True

    def test_env_prefix_drives_env_var_resolution(
        self, monkeypatch,
    ):
        """Setting SHOPAI_FOO_HEALTH_MIN_SAMPLE=10 changes the
        threshold for env_prefix='FOO'."""
        monkeypatch.setenv(
            "SHOPAI_FOO_HEALTH_MIN_SAMPLE", "10",
        )
        # 5 events -> would be enough for default min_sample=5
        # but env raised it to 10 -> still insufficient
        report = analyze_health(
            env_prefix="FOO",
            window_hours=24.0,
            recent_events_fn=(
                lambda **kw: _fake_events(failure_count=5)
            ),
            is_paused_fn=lambda: False,
        )
        assert report.verdict == "healthy"
        assert "insufficient data" in report.reasons[0]


class TestAutoPauseBridge:

    def test_bridge_off_by_default(self, monkeypatch):
        monkeypatch.delenv(
            "SHOPAI_AUTO_PAUSE_TEST_DOMAIN_ON_FAILURE",
            raising=False,
        )
        pause_called = []
        report = maybe_auto_pause(
            env_prefix="TEST_DOMAIN",
            window_hours=24.0,
            recent_events_fn=(
                lambda **kw: _fake_events(failure_count=8)
            ),
            is_paused_fn=lambda: False,
            pause_fn=(
                lambda **kw: pause_called.append(kw)
            ),
        )
        assert report.verdict == "critical"
        assert report.bridge_fired is False
        assert pause_called == []

    def test_bridge_fires_when_gated_critical(
        self, monkeypatch,
    ):
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_TEST_DOMAIN_ON_FAILURE", "1",
        )
        pause_called = []
        report = maybe_auto_pause(
            env_prefix="TEST_DOMAIN",
            window_hours=24.0,
            recent_events_fn=(
                lambda **kw: _fake_events(failure_count=8)
            ),
            is_paused_fn=lambda: False,
            pause_fn=(
                lambda **kw: pause_called.append(kw)
            ),
        )
        assert report.bridge_fired is True
        assert len(pause_called) == 1
        # Auto-resume default is 1h
        assert pause_called[0]["auto_resume_after"] > time.time()

    def test_bridge_idempotent_when_paused(self, monkeypatch):
        monkeypatch.setenv(
            "SHOPAI_AUTO_PAUSE_TEST_DOMAIN_ON_FAILURE", "1",
        )
        pause_called = []
        report = maybe_auto_pause(
            env_prefix="TEST_DOMAIN",
            window_hours=24.0,
            recent_events_fn=(
                lambda **kw: _fake_events(failure_count=8)
            ),
            is_paused_fn=lambda: True,
            pause_fn=(
                lambda **kw: pause_called.append(kw)
            ),
        )
        assert report.bridge_reason == "already_paused"
        assert pause_called == []
