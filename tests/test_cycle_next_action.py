"""Tests for ``core.autonomous.cycle_next_action.recommend``.

Rule-based recommender. Priority order:
  1. errored phase
  2. thrashing
  3. cycle alerts
  4. release candidates
  5. demote candidates + bridge off
  6. ADVANCE refused all
  7. ADVANCE succeeded
  8. all clear
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.autonomous import cycle_next_action as cna


def _summary(**kw):
    defaults = {
        "executed": True,
        "advance": {},
        "defend": {},
        "correlate": {},
    }
    defaults.update(kw)
    return defaults


@pytest.fixture(autouse=True)
def _quiet_subsystems():
    """Default fixtures: no thrashing, no alerts. Tests
    that care override one or both."""
    with patch(
        "core.capability_planner.auto_demote_history."
        "find_thrashing",
        return_value=[],
    ), patch(
        "core.autonomous.cycle_alerts."
        "compute_cycle_alerts",
        return_value=[],
    ):
        yield


class TestRule1ErroredPhase:

    def test_advance_error_returns_investigate(self):
        s = _summary(
            advance={"error": "import_failed: x"},
        )
        rec = cna.recommend(s)
        assert rec.priority == "investigate_error"
        assert "ADVANCE" in rec.detail

    def test_defend_error_returns_investigate(self):
        s = _summary(
            defend={"error": "raised: ValueError"},
        )
        rec = cna.recommend(s)
        assert rec.priority == "investigate_error"
        assert "DEFEND" in rec.detail

    def test_correlate_error_returns_investigate(self):
        s = _summary(
            correlate={"error": "import_failed: y"},
        )
        rec = cna.recommend(s)
        assert rec.priority == "investigate_error"
        assert "CORRELATE" in rec.detail


class TestRule2Thrashing:

    def test_thrashing_overrides_other_signals(self):
        with patch(
            "core.capability_planner.auto_demote_history."
            "find_thrashing",
            return_value=[{"capability": "shaky"}],
        ):
            s = _summary(
                advance={
                    "executed_ok": 5,
                    "refused_reliability": 0,
                    "stores_processed": 5,
                },
            )
            rec = cna.recommend(s)
        assert rec.priority == "clear_thrashing"
        assert "shaky" in rec.detail
        assert "clear-override shaky" in rec.cmd


class TestRule3CycleAlerts:

    def test_low_advance_rate_alert_surfaces(self):
        from core.autonomous.cycle_alerts import CycleAlert
        with patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=[
                CycleAlert(
                    kind="low_advance_rate",
                    detail="20%",
                ),
            ],
        ):
            rec = cna.recommend(_summary())
        assert rec.priority == "address_cycle_alerts"
        assert "low_advance_rate" in rec.detail

    def test_silent_and_stale_alerts_skipped(self):
        """cycle_silent + stale_cycle don't apply mid-cycle
        (we JUST ran). Should fall through to next rule."""
        from core.autonomous.cycle_alerts import CycleAlert
        with patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=[
                CycleAlert(
                    kind="cycle_silent", detail="-",
                ),
                CycleAlert(
                    kind="stale_cycle", detail="-",
                ),
            ],
        ):
            rec = cna.recommend(_summary())
        # No cycle alerts surfaced; falls through to
        # all_clear
        assert rec.priority != "address_cycle_alerts"


class TestRule4ReleaseCandidates:

    def test_recovered_unreleased_suggests_release(self):
        s = _summary(
            defend={
                "recovered_candidates": 2,
                "released": 0,
            },
        )
        rec = cna.recommend(s)
        assert rec.priority == "apply_releases"
        assert "auto-demote-release-candidates --yes" in rec.cmd

    def test_recovered_AND_released_no_recommendation(self):
        """Released already this run -> nothing more to do
        in this lane."""
        s = _summary(
            defend={
                "recovered_candidates": 2,
                "released": 2,
            },
        )
        rec = cna.recommend(s)
        assert rec.priority != "apply_releases"


class TestRule5EnableBridge:

    def test_actionable_demotes_but_gate_off(self):
        s = _summary(
            defend={
                "actionable": 3,
                "gate_enabled": False,
            },
        )
        rec = cna.recommend(s)
        assert rec.priority == "enable_bridge"
        assert "SHOPAI_AUTO_DEMOTE_DEGRADED=1" in rec.detail

    def test_actionable_with_gate_on_no_recommendation(self):
        s = _summary(
            defend={
                "actionable": 3,
                "gate_enabled": True,
                "demoted": 3,  # they would have been demoted
            },
        )
        rec = cna.recommend(s)
        assert rec.priority != "enable_bridge"


class TestRule6ReliabilityTooTight:

    def test_all_refused_suggests_relax(self):
        s = _summary(
            advance={
                "stores_processed": 3,
                "executed_ok": 0,
                "refused_reliability": 3,
                "errored": 0,
            },
        )
        rec = cna.recommend(s)
        assert rec.priority == "relax_reliability"
        assert "fleet-plan" in rec.cmd

    def test_partial_refusal_doesnt_trigger(self):
        s = _summary(
            advance={
                "stores_processed": 3,
                "executed_ok": 1,
                "refused_reliability": 2,
                "errored": 0,
            },
        )
        rec = cna.recommend(s)
        # 1 advanced -> falls to measure rule, not relax
        assert rec.priority != "relax_reliability"


class TestRule7MeasureOutcomes:

    def test_advanced_stores_suggests_correlate(self):
        s = _summary(
            advance={
                "stores_processed": 2,
                "executed_ok": 2,
                "refused_reliability": 0,
                "errored": 0,
            },
        )
        rec = cna.recommend(s)
        assert rec.priority == "measure_outcomes"
        assert "--auto-correlate" in rec.cmd


class TestRule8AllClear:

    def test_quiet_summary_returns_all_clear(self):
        s = _summary(
            advance={
                "stores_processed": 0,
                "executed_ok": 0,
                "refused_reliability": 0,
                "errored": 0,
            },
            defend={"actionable": 0},
            correlate={"correlated": 0},
        )
        rec = cna.recommend(s)
        assert rec.priority == "all_clear"


class TestResilience:

    def test_non_dict_summary_returns_investigate(self):
        rec = cna.recommend(None)
        assert rec.priority == "investigate"

    def test_thrashing_lookup_failure_continues(self):
        with patch(
            "core.capability_planner.auto_demote_history."
            "find_thrashing",
            side_effect=RuntimeError("disk"),
        ):
            s = _summary(
                advance={"executed_ok": 1},
            )
            rec = cna.recommend(s)
        # Falls through to measure_outcomes
        assert rec.priority == "measure_outcomes"
