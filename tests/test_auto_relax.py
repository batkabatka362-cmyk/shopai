"""Tests for ``core.autonomous.auto_relax``.

Auto-relax / auto-restore bridge for the reliability
threshold. Reads cycle_alert_history streaks +
cycle_overrides state; writes back via set_override when
env gate is set.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.autonomous import auto_relax as ar


_ENV_VARS = (
    "SHOPAI_AUTO_RELAX_RELIABILITY",
    "SHOPAI_AUTO_RELAX_STREAK_DAYS",
    "SHOPAI_AUTO_RELAX_STEP",
    "SHOPAI_AUTO_RELAX_FLOOR",
    "SHOPAI_AUTO_RELAX_QUIET_DAYS",
    "SHOPAI_AUTO_RELAX_CEILING",
)


@pytest.fixture(autouse=True)
def _clean_env():
    saved = {k: os.environ.pop(k, None) for k in _ENV_VARS}
    yield
    for k in _ENV_VARS:
        os.environ.pop(k, None)
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


class TestEnvGates:

    def test_defaults(self):
        assert ar.is_enabled() is False
        assert ar.streak_days_threshold() == 3
        assert ar.relax_step() == 0.05
        assert ar.relax_floor() == 0.5
        assert ar.quiet_days_threshold() == 5
        assert ar.relax_ceiling() == 0.9

    def test_env_overrides(self):
        os.environ["SHOPAI_AUTO_RELAX_RELIABILITY"] = "1"
        os.environ["SHOPAI_AUTO_RELAX_STREAK_DAYS"] = "5"
        os.environ["SHOPAI_AUTO_RELAX_STEP"] = "0.1"
        os.environ["SHOPAI_AUTO_RELAX_FLOOR"] = "0.3"
        os.environ["SHOPAI_AUTO_RELAX_QUIET_DAYS"] = "10"
        os.environ["SHOPAI_AUTO_RELAX_CEILING"] = "0.95"
        assert ar.is_enabled() is True
        assert ar.streak_days_threshold() == 5
        assert ar.relax_step() == 0.1
        assert ar.relax_floor() == 0.3
        assert ar.quiet_days_threshold() == 10
        assert ar.relax_ceiling() == 0.95

    def test_streak_min_2(self):
        os.environ["SHOPAI_AUTO_RELAX_STREAK_DAYS"] = "1"
        assert ar.streak_days_threshold() == 2

    def test_step_out_of_range_falls_back(self):
        os.environ["SHOPAI_AUTO_RELAX_STEP"] = "0.8"
        assert ar.relax_step() == 0.05
        os.environ["SHOPAI_AUTO_RELAX_STEP"] = "-0.1"
        assert ar.relax_step() == 0.05

    def test_config_summary(self):
        cfg = ar.config_summary()
        assert "enabled" in cfg
        assert cfg["streak_days_threshold"] == 3


class TestFindRelaxAction:

    def test_no_streak_returns_none(self):
        with patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={},
        ), patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.9,
        ):
            action = ar.find_relax_action()
        assert action.direction == "none"
        assert action.current_value == 0.9

    def test_streak_below_threshold_no_relax(self):
        with patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={"low_advance_rate": 2},
        ), patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.9,
        ):
            action = ar.find_relax_action()
        assert action.direction == "none"

    def test_streak_at_threshold_proposes_relax(self):
        with patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={"low_advance_rate": 3},
        ), patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.9,
        ):
            action = ar.find_relax_action()
        assert action.direction == "relax"
        assert action.current_value == 0.9
        # 0.9 - 0.05 = 0.85
        assert action.proposed_value == 0.85
        assert "3d" in action.reason

    def test_floor_caps_relax(self):
        """Threshold already at the floor -- no further
        relax proposed."""
        with patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={"low_advance_rate": 5},
        ), patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.5,
        ):
            action = ar.find_relax_action()
        assert action.direction == "none"
        assert "floor" in action.reason

    def test_proposed_clamps_at_floor(self):
        """If current is just above the floor, proposed
        clamps AT the floor not below."""
        with patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={"low_advance_rate": 5},
        ), patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.52,  # close to floor 0.5
        ):
            action = ar.find_relax_action()
        assert action.direction == "relax"
        assert action.proposed_value == 0.5


class TestFindRestoreAction:

    def _w_overrides(self, overrides):
        return patch(
            "core.autonomous.cycle_overrides."
            "load_overrides",
            return_value=overrides,
        )

    def test_at_ceiling_no_restore(self):
        with patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.9,
        ), self._w_overrides({}):
            action = ar.find_restore_action()
        assert action.direction == "none"
        assert "ceiling" in action.reason

    def test_no_persistent_override_no_restore(self):
        """If a prior relax never wrote the override file,
        restore doesn't fire (we don't touch operator's env
        / default value)."""
        with patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.7,
        ), self._w_overrides({}):
            action = ar.find_restore_action()
        assert action.direction == "none"
        assert "no persistent override" in action.reason

    def test_recent_fires_no_restore(self):
        with patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.7,
        ), self._w_overrides({
            "auto_execute_threshold": 0.7,
        }), patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={"low_advance_rate": 2},
        ):
            action = ar.find_restore_action()
        assert action.direction == "none"
        assert "fired in last" in action.reason

    def test_quiet_proposes_restore(self):
        with patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.7,
        ), self._w_overrides({
            "auto_execute_threshold": 0.7,
        }), patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={},  # No firings
        ):
            action = ar.find_restore_action()
        assert action.direction == "restore"
        assert action.proposed_value == 0.75
        assert "quiet for" in action.reason

    def test_proposed_clamps_at_ceiling(self):
        with patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.88,
        ), self._w_overrides({
            "auto_execute_threshold": 0.88,
        }), patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={},
        ):
            action = ar.find_restore_action()
        assert action.direction == "restore"
        # 0.88 + 0.05 = 0.93 -> clamps to ceiling 0.9
        assert action.proposed_value == 0.9


class TestMaybeApply:

    def test_pattern_j_short_circuits(self):
        """Under pytest, maybe_apply doesn't write even if
        env gate is on."""
        os.environ["SHOPAI_AUTO_RELAX_RELIABILITY"] = "1"
        action = ar.RelaxAction(
            direction="relax",
            current_value=0.9,
            proposed_value=0.85,
            reason="x",
        )
        with patch(
            "core.autonomous.cycle_overrides."
            "set_override",
        ) as mock_set:
            result = ar.maybe_apply(action)
        assert result.applied is False
        mock_set.assert_not_called()

    def test_env_gate_off_no_write(self):
        action = ar.RelaxAction(
            direction="relax",
            current_value=0.9,
            proposed_value=0.85,
            reason="x",
        )
        with patch(
            "core.autonomous.auto_relax."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.autonomous.cycle_overrides."
            "set_override",
        ) as mock_set:
            result = ar.maybe_apply(action)
        assert result.applied is False
        mock_set.assert_not_called()

    def test_direction_none_no_op(self):
        action = ar.RelaxAction(
            direction="none",
            current_value=0.9,
            proposed_value=0.9,
            reason="x",
        )
        with patch(
            "core.autonomous.cycle_overrides."
            "set_override",
        ) as mock_set:
            result = ar.maybe_apply(action)
        assert result.applied is False
        mock_set.assert_not_called()

    def test_enabled_writes_through(self):
        os.environ["SHOPAI_AUTO_RELAX_RELIABILITY"] = "1"
        action = ar.RelaxAction(
            direction="relax",
            current_value=0.9,
            proposed_value=0.85,
            reason="x",
        )
        with patch(
            "core.autonomous.auto_relax."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.autonomous.cycle_overrides."
            "set_override",
            return_value=True,
        ) as mock_set:
            result = ar.maybe_apply(action)
        assert result.applied is True
        mock_set.assert_called_once_with(
            "auto_execute_threshold", 0.85,
        )


class TestMaybeRelaxAndRestore:

    def test_returns_summary_dict_shape(self):
        with patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={},
        ), patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.9,
        ), patch(
            "core.autonomous.cycle_overrides."
            "load_overrides",
            return_value={},
        ):
            out = ar.maybe_relax_and_restore()
        assert out["checked"] is True
        assert out["direction"] == "none"
        assert out["applied"] is False

    def test_restore_checked_before_relax(self):
        """Restore short-circuits when conditions hold,
        without computing relax."""
        with patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.7,
        ), patch(
            "core.autonomous.cycle_overrides."
            "load_overrides",
            return_value={
                "auto_execute_threshold": 0.7,
            },
        ), patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={},
        ):
            out = ar.maybe_relax_and_restore()
        assert out["direction"] == "restore"

    def test_relax_fires_when_streak_persistent(self):
        with patch(
            "core.autonomous.cycle_alert_history."
            "consecutive_days_per_kind",
            return_value={"low_advance_rate": 4},
        ), patch(
            "core.autonomous.cycle_overrides."
            "resolve_threshold",
            return_value=0.9,
        ), patch(
            "core.autonomous.cycle_overrides."
            "load_overrides",
            return_value={},
        ):
            out = ar.maybe_relax_and_restore()
        assert out["direction"] == "relax"
        assert out["current_value"] == 0.9
        assert out["proposed_value"] == 0.85
