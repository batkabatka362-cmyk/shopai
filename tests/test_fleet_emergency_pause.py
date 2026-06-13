"""Tests for engines.fleet_emergency_pause — W963-32."""
from __future__ import annotations

from unittest.mock import patch

from engines.fleet_emergency_pause import (
    FleetEmergencyPauseEngine,
)
from engines.fleet_emergency_pause import state as state_mod


# ── state module ──────────────────────────────────────────


class TestState:
    def test_empty_default_unpaused(self, tmp_path):
        state_mod.reset_path(tmp_path / "fe.json")
        assert state_mod.is_paused() is False
        s = state_mod.get_state()
        assert s["paused"] is False

    def test_get_state_returns_defaults(self, tmp_path):
        state_mod.reset_path(tmp_path / "fe.json")
        s = state_mod.get_state()
        for k in ("paused", "paused_at", "paused_by", "reason"):
            assert k in s

    def test_set_paused_blocked_in_test_env(self, tmp_path):
        # Pattern J guard: under pytest, set_paused returns
        # False without writing.
        state_mod.reset_path(tmp_path / "fe.json")
        ok = state_mod.set_paused(reason="x", by="me")
        assert ok is False
        # State stays unpaused
        assert state_mod.is_paused() is False

    def test_clear_paused_blocked_in_test_env(self, tmp_path):
        state_mod.reset_path(tmp_path / "fe.json")
        ok = state_mod.clear_paused()
        assert ok is False


# ── Engine envelope ────────────────────────────────────────


class TestEnvelope:
    def test_empty_success(self):
        r = FleetEmergencyPauseEngine().run({})
        assert r["status"] == "success"
        # Default action is status
        assert r["data"]["action"] == "status"

    def test_none_success(self):
        r = FleetEmergencyPauseEngine().run(None)
        assert r["status"] == "success"

    def test_non_dict_error(self):
        r = FleetEmergencyPauseEngine().run("nope")
        assert r["status"] == "error"

    def test_fail_upstream(self):
        r = FleetEmergencyPauseEngine().run({
            "status": "fail", "error": "broken",
        })
        assert r["status"] == "error"

    def test_unknown_action_error(self):
        r = FleetEmergencyPauseEngine().run({
            "data": {"action": "blast"},
        })
        assert r["status"] == "error"

    def test_carries_engine_name(self):
        r = FleetEmergencyPauseEngine().run({})
        assert r["meta"]["engine"] == "fleet_emergency_pause"


class TestStatusAction:
    def test_status_active(self, tmp_path):
        state_mod.reset_path(tmp_path / "fe.json")
        r = FleetEmergencyPauseEngine().run({
            "data": {"action": "status"},
        })
        assert r["data"]["paused"] is False
        assert "Fleet ACTIVE" in r["data"]["next_action"]


class TestPauseAction:
    def test_pause_without_yes_is_dry_run(self, tmp_path):
        state_mod.reset_path(tmp_path / "fe.json")
        r = FleetEmergencyPauseEngine().run({
            "data": {"action": "pause"},
        })
        assert r["data"]["fired"] is False
        assert r["data"]["skip_reason"] == "dry_run"

    def test_pause_with_yes_blocked_by_pattern_j(
        self, tmp_path,
    ):
        # Pattern J under pytest -> set_paused returns False,
        # so fired=False even with --yes.
        state_mod.reset_path(tmp_path / "fe.json")
        r = FleetEmergencyPauseEngine().run({
            "data": {
                "action": "pause", "confirmed": True,
                "reason": "test",
            },
        })
        assert r["data"]["fired"] is False
        assert r["data"]["skip_reason"] == "test_env_or_io"

    def test_pause_with_yes_outside_test_env(
        self, tmp_path,
    ):
        # Force production-writes override to bypass Pattern J
        state_mod.reset_path(tmp_path / "fe.json")
        with patch.object(
            state_mod, "_is_test_environment",
            return_value=False,
        ):
            r = FleetEmergencyPauseEngine().run({
                "data": {
                    "action": "pause", "confirmed": True,
                    "reason": "fraud spike",
                    "by": "operator",
                },
            })
        assert r["data"]["paused"] is True
        assert r["data"]["fired"] is True
        assert r["data"]["reason"] == "fraud spike"
        assert "RESUMED" not in r["data"]["next_action"]


class TestResumeAction:
    def test_resume_without_yes_is_dry_run(self, tmp_path):
        state_mod.reset_path(tmp_path / "fe.json")
        r = FleetEmergencyPauseEngine().run({
            "data": {"action": "resume"},
        })
        assert r["data"]["fired"] is False
        assert r["data"]["skip_reason"] == "dry_run"

    def test_resume_lifts_marker(self, tmp_path):
        state_mod.reset_path(tmp_path / "fe.json")
        # Pause first (with override)
        with patch.object(
            state_mod, "_is_test_environment",
            return_value=False,
        ):
            FleetEmergencyPauseEngine().run({
                "data": {
                    "action": "pause", "confirmed": True,
                    "reason": "test",
                },
            })
            assert state_mod.is_paused() is True
            r = FleetEmergencyPauseEngine().run({
                "data": {
                    "action": "resume", "confirmed": True,
                },
            })
        assert r["data"]["paused"] is False
        assert r["data"]["fired"] is True
        assert state_mod.is_paused() is False


# ── Autopilot integration ──────────────────────────────────


class TestAutopilotIntegration:
    def test_autopilot_writers_skip_when_marker_set(
        self, tmp_path,
    ):
        # When marker is set, autopilot welcome+reviews force
        # to disabled regardless of operator confirmation.
        from engines.autopilot.runner import run_autopilot
        with patch(
            "engines.autopilot.runner._fleet_emergency_paused",
            return_value=True,
        ):
            report = run_autopilot(
                confirmed=True, store_id=None,
            )
        # Welcome + reviews should be disabled
        names = {
            s.name: s for s in report.stages
        }
        assert names["welcome"].verdict == "disabled"
        assert names["reviews"].verdict == "disabled"
        # And their detail mentions the marker
        assert (
            "emergency"
            in names["welcome"].detail.lower()
        )

    def test_autopilot_writers_fire_when_marker_unset(
        self, tmp_path,
    ):
        # When marker is unset, autopilot writers respect
        # their own env gates (welcome/reviews default OFF).
        from engines.autopilot.runner import run_autopilot
        with patch(
            "engines.autopilot.runner._fleet_emergency_paused",
            return_value=False,
        ):
            report = run_autopilot(
                confirmed=False, store_id=None,
            )
        names = {
            s.name: s for s in report.stages
        }
        # Welcome/reviews stay disabled because their
        # own env gates default OFF -- but NOT due to
        # emergency pause.
        assert (
            "emergency"
            not in names["welcome"].detail.lower()
        )
