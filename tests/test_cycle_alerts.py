"""Tests for ``core.autonomous.cycle_alerts``.

Four alert kinds: stale_cycle / cycle_silent /
low_advance_rate / substrate_shrinking. Each test mocks
``cycle_stats`` so we don't touch the persistence layer
(those are exercised by test_cycle_history + the e2e test).
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.autonomous import cycle_alerts as ca


_ENV_VARS = (
    "SHOPAI_CYCLE_STALE_HOURS",
    "SHOPAI_CYCLE_MIN_ADVANCE_RATE",
    "SHOPAI_CYCLE_DEMOTE_RATIO_LIMIT",
)


@pytest.fixture(autouse=True)
def _clean_env():
    preserved = {k: os.environ.pop(k, None) for k in _ENV_VARS}
    yield
    for k in _ENV_VARS:
        os.environ.pop(k, None)
    for k, v in preserved.items():
        if v is not None:
            os.environ[k] = v


def _stats(**kw):
    defaults = dict(
        total_runs=0,
        executed_runs=0,
        dry_run_count=0,
        last_run_at=None,
        stores_advanced_total=0,
        stores_refused_total=0,
        demoted_total=0,
        released_total=0,
        correlated_total=0,
    )
    defaults.update(kw)
    return defaults


class TestEnvGates:

    def test_defaults(self):
        assert ca.stale_hours_threshold() == 24
        assert ca.min_advance_rate_threshold() == 0.5
        assert ca.demote_ratio_limit() == 5.0

    def test_env_overrides(self):
        os.environ["SHOPAI_CYCLE_STALE_HOURS"] = "12"
        os.environ["SHOPAI_CYCLE_MIN_ADVANCE_RATE"] = "0.75"
        os.environ["SHOPAI_CYCLE_DEMOTE_RATIO_LIMIT"] = "10"
        assert ca.stale_hours_threshold() == 12
        assert ca.min_advance_rate_threshold() == 0.75
        assert ca.demote_ratio_limit() == 10.0

    def test_bad_values_fall_back(self):
        os.environ["SHOPAI_CYCLE_STALE_HOURS"] = "abc"
        os.environ["SHOPAI_CYCLE_MIN_ADVANCE_RATE"] = "2.0"
        os.environ["SHOPAI_CYCLE_DEMOTE_RATIO_LIMIT"] = "0.5"
        assert ca.stale_hours_threshold() == 24
        assert ca.min_advance_rate_threshold() == 0.5
        assert ca.demote_ratio_limit() == 5.0

    def test_config_summary(self):
        cfg = ca.config_summary()
        assert "stale_hours_threshold" in cfg
        assert "min_advance_rate_threshold" in cfg
        assert "demote_ratio_limit" in cfg


class TestCycleSilent:

    def test_fires_when_total_runs_zero(self):
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(total_runs=0),
        ):
            alerts = ca.compute_cycle_alerts()
        assert len(alerts) == 1
        assert alerts[0].kind == "cycle_silent"
        assert "No cycle runs" in alerts[0].detail

    def test_silent_skips_other_alerts(self):
        """When silent, other alerts shouldn't ALSO fire --
        they don't have meaningful data."""
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=0,
                # These shouldn't matter since total=0
                last_run_at=None,
                demoted_total=100,
                released_total=0,
            ),
        ):
            alerts = ca.compute_cycle_alerts()
        kinds = [a.kind for a in alerts]
        assert kinds == ["cycle_silent"]


class TestStaleCycle:

    def test_fires_when_last_run_old(self):
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=1,
                executed_runs=1,
                last_run_at=now - 86400 * 2,  # 48h ago
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "stale_cycle" in kinds

    def test_no_alert_when_recent(self):
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=1,
                executed_runs=1,
                last_run_at=now - 1800,  # 30 min ago
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "stale_cycle" not in kinds

    def test_env_threshold_respected(self):
        import time as _t
        os.environ["SHOPAI_CYCLE_STALE_HOURS"] = "1"
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=1,
                executed_runs=1,
                last_run_at=now - 7200,  # 2h ago
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        # 2h > 1h threshold
        kinds = [a.kind for a in alerts]
        assert "stale_cycle" in kinds


class TestLowAdvanceRate:

    def test_fires_when_rate_below_threshold(self):
        import time as _t
        now = _t.time()
        # 3 executed cycles, 1 advanced + 4 refused = 20%
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=3,
                executed_runs=3,
                last_run_at=now - 60,
                stores_advanced_total=1,
                stores_refused_total=4,
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "low_advance_rate" in kinds

    def test_no_alert_when_rate_healthy(self):
        import time as _t
        now = _t.time()
        # 90% advance rate
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=3,
                executed_runs=3,
                last_run_at=now - 60,
                stores_advanced_total=9,
                stores_refused_total=1,
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "low_advance_rate" not in kinds

    def test_min_3_executed_cycles_required(self):
        """A single bad cycle doesn't trigger the alert --
        need at least 3 to have signal."""
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=1,
                executed_runs=1,
                last_run_at=now - 60,
                stores_advanced_total=0,
                stores_refused_total=5,
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "low_advance_rate" not in kinds


class TestSubstrateShrinking:

    def test_fires_when_demote_ratio_high(self):
        import time as _t
        now = _t.time()
        # 10 demoted, 1 released = 10x ratio (default limit 5x)
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=5,
                executed_runs=5,
                last_run_at=now - 60,
                demoted_total=10,
                released_total=1,
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "substrate_shrinking" in kinds

    def test_no_alert_when_balanced(self):
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=5,
                executed_runs=5,
                last_run_at=now - 60,
                demoted_total=5,
                released_total=4,
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "substrate_shrinking" not in kinds

    def test_min_3_demotes_required(self):
        """Single demote isn't a trend."""
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=2,
                executed_runs=2,
                last_run_at=now - 60,
                demoted_total=2,
                released_total=0,
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "substrate_shrinking" not in kinds


class TestMultipleAlerts:

    def test_multiple_can_fire_simultaneously(self):
        """stale + low_advance + shrinking can all fire at
        once when the cycle has been running but badly."""
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(
                total_runs=5,
                executed_runs=5,
                last_run_at=now - 86400 * 2,  # stale
                stores_advanced_total=1,
                stores_refused_total=9,  # 10% rate
                demoted_total=10,
                released_total=1,  # 10x ratio
            ),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = {a.kind for a in alerts}
        assert "stale_cycle" in kinds
        assert "low_advance_rate" in kinds
        assert "substrate_shrinking" in kinds

    def test_stats_failure_returns_empty(self):
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            side_effect=RuntimeError("disk"),
        ):
            alerts = ca.compute_cycle_alerts()
        assert alerts == []
