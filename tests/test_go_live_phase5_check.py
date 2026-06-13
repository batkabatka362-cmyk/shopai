"""Tests for go-live Phase 5 autonomy check (W963-83)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from unittest.mock import patch

from engines._go_live_check import (
    _check_phase5_autonomy,
    run_go_live_check,
)


@dataclass
class _FakeArmReport:
    verdict: str = "no_data"


class TestPhase5Check:
    def test_pass_when_enabled(self):
        with patch.dict(
            os.environ,
            {"SHOPAI_AUTO_DISARM_ON_OVERRIDE": "1"},
            clear=False,
        ), patch(
            "engines.agi_arm_recommender.recommender."
            "recommend",
            return_value=_FakeArmReport(),
        ):
            r = _check_phase5_autonomy()
        assert r.status == "pass"
        assert "auto-disarm enabled" in r.detail

    def test_warn_when_disabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(
                "SHOPAI_AUTO_DISARM_ON_OVERRIDE", None,
            )
            with patch(
                "engines.agi_arm_recommender.recommender."
                "recommend",
                return_value=_FakeArmReport(),
            ):
                r = _check_phase5_autonomy()
        assert r.status == "warn"
        assert "auto-disarm OFF" in r.detail
        assert (
            "SHOPAI_AUTO_DISARM_ON_OVERRIDE" in r.fix
        )

    def test_fail_when_recommender_raises(self):
        with patch(
            "engines.agi_arm_recommender.recommender."
            "recommend",
            side_effect=RuntimeError("boom"),
        ):
            r = _check_phase5_autonomy()
        assert r.status == "fail"
        assert "boom" in r.detail


class TestRosterIntegration:
    def test_phase5_check_appended(self):
        results = run_go_live_check()
        names = [r.name for r in results]
        assert "phase5_autonomy" in names

    def test_phase5_is_last(self):
        results = run_go_live_check()
        names = [r.name for r in results]
        # phase5 added after phase4 → last
        assert names[-1] == "phase5_autonomy"
