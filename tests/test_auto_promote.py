"""Tests for ``core.capability_planner.auto_promote``."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.capability_planner import auto_promote as ap


_ENV_VARS = (
    "SHOPAI_AUTO_PROMOTE_RELIABLE",
    "SHOPAI_AUTO_PROMOTE_THRESHOLD",
    "SHOPAI_AUTO_PROMOTE_MIN_SAMPLE",
    "SHOPAI_AUTO_PROMOTE_WINDOW_DAYS",
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


def _overrides(promoted=None, demoted=None):
    from core.capability_planner.\
capability_overrides import (
        CapabilityOverride, CapabilityOverrides,
    )
    entries = []
    for n in (promoted or []):
        entries.append(CapabilityOverride(
            name=n, kind="promote",
        ))
    for n in (demoted or []):
        entries.append(CapabilityOverride(
            name=n, kind="demote",
        ))
    return CapabilityOverrides(entries=entries)


class TestEnvGates:

    def test_defaults(self):
        assert ap.is_enabled() is False
        assert ap.threshold() == 0.95
        assert ap.min_sample() == 5
        assert ap.window_days() == 30

    def test_env_overrides(self):
        os.environ["SHOPAI_AUTO_PROMOTE_RELIABLE"] = "1"
        os.environ["SHOPAI_AUTO_PROMOTE_THRESHOLD"] = "0.85"
        os.environ["SHOPAI_AUTO_PROMOTE_MIN_SAMPLE"] = "10"
        os.environ["SHOPAI_AUTO_PROMOTE_WINDOW_DAYS"] = "60"
        assert ap.is_enabled() is True
        assert ap.threshold() == 0.85
        assert ap.min_sample() == 10
        assert ap.window_days() == 60

    def test_invalid_falls_back(self):
        os.environ["SHOPAI_AUTO_PROMOTE_THRESHOLD"] = "2.0"
        assert ap.threshold() == 0.95
        os.environ["SHOPAI_AUTO_PROMOTE_THRESHOLD"] = "-0.1"
        assert ap.threshold() == 0.95

    def test_config_summary(self):
        cfg = ap.config_summary()
        assert cfg["enabled"] is False
        assert cfg["threshold"] == 0.95


class TestFindPromoteCandidates:

    def test_no_history_empty(self):
        with patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=[],
        ):
            out = ap.find_promote_candidates()
        assert out == []

    def test_below_threshold_skipped(self):
        rows = [{
            "capability": "cap_a",
            "executed_count": 5,
            "success_count": 4,
            "success_rate": 0.8,  # below 0.95
        }]
        with patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(),
        ):
            out = ap.find_promote_candidates()
        assert out == []

    def test_qualifying_cap_returned(self):
        rows = [{
            "capability": "winner",
            "executed_count": 10,
            "success_count": 10,
            "success_rate": 1.0,
        }]
        with patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(),
        ):
            out = ap.find_promote_candidates()
        assert len(out) == 1
        assert out[0]["capability"] == "winner"
        assert out[0]["blocked_by"] is None

    def test_already_promoted_blocked(self):
        rows = [{
            "capability": "winner",
            "executed_count": 10,
            "success_count": 10,
            "success_rate": 1.0,
        }]
        with patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(promoted=["winner"]),
        ):
            out = ap.find_promote_candidates()
        assert len(out) == 1
        assert out[0]["blocked_by"] == "already_promoted"

    def test_demoted_blocked(self):
        """Demote signal trumps auto-promote -- never undo
        a demote autonomously."""
        rows = [{
            "capability": "cap_a",
            "executed_count": 10,
            "success_count": 10,
            "success_rate": 1.0,
        }]
        with patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(demoted=["cap_a"]),
        ):
            out = ap.find_promote_candidates()
        assert out[0]["blocked_by"] == "demoted"

    def test_overrides_passed_through(self):
        called = {}

        def fake_leaderboard(**kwargs):
            called.update(kwargs)
            return []

        with patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            side_effect=fake_leaderboard,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(),
        ):
            ap.find_promote_candidates(
                threshold_override=0.85,
                min_sample_override=3,
                window_days_override=14,
            )
        assert called["min_sample_size"] == 3
        assert called["since_seconds"] == 14 * 86400


class TestMaybeAutoPromote:

    def test_pattern_j_short_circuits(self):
        os.environ["SHOPAI_AUTO_PROMOTE_RELIABLE"] = "1"
        rows = [{
            "capability": "winner",
            "executed_count": 10,
            "success_count": 10,
            "success_rate": 1.0,
        }]
        with patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(),
        ):
            applied = ap.maybe_auto_promote_reliable()
        assert applied == []

    def test_disabled_no_write(self):
        rows = [{
            "capability": "winner",
            "executed_count": 10,
            "success_count": 10,
            "success_rate": 1.0,
        }]
        with patch(
            "core.capability_planner.auto_promote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(),
        ), patch(
            "core.capability_planner.capability_overrides."
            "promote",
        ) as mock_promote:
            applied = ap.maybe_auto_promote_reliable()
        assert applied == []
        mock_promote.assert_not_called()

    def test_enabled_applies(self):
        os.environ["SHOPAI_AUTO_PROMOTE_RELIABLE"] = "1"
        rows = [{
            "capability": "winner",
            "executed_count": 10,
            "success_count": 10,
            "success_rate": 1.0,
        }]
        with patch(
            "core.capability_planner.auto_promote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(),
        ), patch(
            "core.capability_planner.capability_overrides."
            "promote",
            return_value=True,
        ) as mock_promote:
            applied = ap.maybe_auto_promote_reliable()
        assert len(applied) == 1
        assert applied[0]["capability"] == "winner"
        mock_promote.assert_called_once()

    def test_blocked_caps_skipped_on_apply(self):
        os.environ["SHOPAI_AUTO_PROMOTE_RELIABLE"] = "1"
        rows = [
            {
                "capability": "winner",
                "executed_count": 10,
                "success_count": 10,
                "success_rate": 1.0,
            },
            {
                "capability": "demoted_one",
                "executed_count": 10,
                "success_count": 10,
                "success_rate": 1.0,
            },
            {
                "capability": "already_promoted",
                "executed_count": 10,
                "success_count": 10,
                "success_rate": 1.0,
            },
        ]
        with patch(
            "core.capability_planner.auto_promote."
            "_is_test_environment",
            return_value=False,
        ), patch(
            "core.capability_planner.plan_history."
            "capability_leaderboard",
            return_value=rows,
        ), patch(
            "core.capability_planner.capability_overrides."
            "load_overrides",
            return_value=_overrides(
                demoted=["demoted_one"],
                promoted=["already_promoted"],
            ),
        ), patch(
            "core.capability_planner.capability_overrides."
            "promote",
            return_value=True,
        ) as mock_promote:
            applied = ap.maybe_auto_promote_reliable()
        # Only winner gets promoted
        assert len(applied) == 1
        assert applied[0]["capability"] == "winner"
        # Only ONE promote() call (for winner)
        assert mock_promote.call_count == 1
