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


class TestPerStoreCycleAlerts:
    """Per-store cycle alerts -- detect store-level health
    issues separately from fleet-wide patterns."""

    def _stats_map(self, **stores):
        """Build a fake per_store_stats dict. Each kwarg is
        store_id=(executed, refused, errored, no_plan)."""
        out = {}
        for sid, vals in stores.items():
            executed, refused, errored, no_plan = vals
            out[sid] = {
                "executed": executed,
                "refused": refused,
                "errored": errored,
                "no_plan": no_plan,
                "total": (
                    executed + refused
                    + errored + no_plan
                ),
            }
        return out

    def test_empty_returns_empty(self):
        with patch(
            "core.autonomous.cycle_history."
            "per_store_stats",
            return_value={},
        ):
            alerts = ca.compute_per_store_alerts()
        assert alerts == []

    def test_skip_below_min_attempts(self):
        """Only 2 attempts -- below default min_attempts=3."""
        with patch(
            "core.autonomous.cycle_history."
            "per_store_stats",
            return_value=self._stats_map(
                store_a=(0, 2, 0, 0),
            ),
        ):
            alerts = ca.compute_per_store_alerts()
        assert alerts == []

    def test_consistently_refused_fires(self):
        # 3 attempts, all refused -> 0% advance rate
        with patch(
            "core.autonomous.cycle_history."
            "per_store_stats",
            return_value=self._stats_map(
                store_a=(0, 3, 0, 0),
            ),
        ):
            alerts = ca.compute_per_store_alerts()
        kinds = {(a.store_id, a.kind) for a in alerts}
        assert (
            ("store_a", "store_consistently_refused")
            in kinds
        )

    def test_consistently_errored_fires(self):
        # 4 errored / 5 total -> 80% error rate
        with patch(
            "core.autonomous.cycle_history."
            "per_store_stats",
            return_value=self._stats_map(
                store_a=(1, 0, 4, 0),
            ),
        ):
            alerts = ca.compute_per_store_alerts()
        kinds = {(a.store_id, a.kind) for a in alerts}
        assert (
            ("store_a", "store_consistently_errored")
            in kinds
        )

    def test_errored_takes_precedence_over_refused(self):
        """When both signals fire, prefer the errored
        signal (root cause is infra, not substrate)."""
        with patch(
            "core.autonomous.cycle_history."
            "per_store_stats",
            return_value=self._stats_map(
                # 5 errored + 0 executed + 5 refused = 10
                # total; error rate 50% -> errored fires;
                # refused doesn't (errored short-circuits)
                store_a=(0, 5, 5, 0),
            ),
        ):
            alerts = ca.compute_per_store_alerts()
        kinds = [a.kind for a in alerts]
        assert "store_consistently_errored" in kinds
        assert "store_consistently_refused" not in kinds

    def test_healthy_store_no_alert(self):
        # 5 executed of 5 -> 100% advance rate
        with patch(
            "core.autonomous.cycle_history."
            "per_store_stats",
            return_value=self._stats_map(
                store_a=(5, 0, 0, 0),
            ),
        ):
            alerts = ca.compute_per_store_alerts()
        assert alerts == []

    def test_multiple_stores_multiple_alerts(self):
        with patch(
            "core.autonomous.cycle_history."
            "per_store_stats",
            return_value=self._stats_map(
                healthy_store=(5, 0, 0, 0),
                refused_store=(0, 4, 0, 0),
                errored_store=(0, 0, 3, 0),
            ),
        ):
            alerts = ca.compute_per_store_alerts()
        store_kinds = {
            (a.store_id, a.kind) for a in alerts
        }
        assert (
            ("refused_store", "store_consistently_refused")
            in store_kinds
        )
        assert (
            ("errored_store", "store_consistently_errored")
            in store_kinds
        )
        # healthy_store has no entry
        assert all(
            a.store_id != "healthy_store" for a in alerts
        )

    def test_stats_failure_returns_empty(self):
        with patch(
            "core.autonomous.cycle_history."
            "per_store_stats",
            side_effect=RuntimeError("disk"),
        ):
            alerts = ca.compute_per_store_alerts()
        assert alerts == []


class TestPromoteDemoteThrashingAlert:
    """When promote-demote cycles exist, surface as a
    cycle alert."""

    def test_no_thrashing_no_alert(self):
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(total_runs=1),
        ), patch(
            "core.capability_planner.auto_promote."
            "find_promote_demote_cycles",
            return_value=[],
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "promote_demote_thrashing" not in kinds

    def test_thrashing_fires_alert(self):
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(total_runs=1),
        ), patch(
            "core.capability_planner.auto_promote."
            "find_promote_demote_cycles",
            return_value=[
                {
                    "capability": "shaky_a",
                    "promote_count": 2,
                    "demote_count": 2,
                    "total_events": 4,
                    "first_event_at": 0.0,
                    "last_event_at": 1.0,
                },
            ],
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        kinds = [a.kind for a in alerts]
        assert "promote_demote_thrashing" in kinds
        thrash_alert = next(
            a for a in alerts
            if a.kind == "promote_demote_thrashing"
        )
        assert "shaky_a" in thrash_alert.detail
        assert thrash_alert.metrics["count"] == 1

    def test_lookup_failure_skipped(self):
        import time as _t
        now = _t.time()
        with patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=_stats(total_runs=1),
        ), patch(
            "core.capability_planner.auto_promote."
            "find_promote_demote_cycles",
            side_effect=RuntimeError("disk"),
        ):
            alerts = ca.compute_cycle_alerts(now=now)
        # Other alerts may still fire, but no thrashing
        kinds = [a.kind for a in alerts]
        assert "promote_demote_thrashing" not in kinds


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
