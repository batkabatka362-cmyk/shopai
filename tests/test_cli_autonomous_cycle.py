"""Tests for ``shopai autonomous-cycle``.

Bundled operator workflow: advance the fleet + measure
outcomes in one command. Cron-friendly. Default dry-run;
``--yes`` opts in to actual writes.

Coverage:
  - Default dry-run reports both phases
  - --skip-advance / --skip-correlate isolate phases
  - --json carries the summary
  - Per-store error isolation
  - Phase-level error surfaces in summary
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


@pytest.fixture(autouse=True)
def _registry_isolation():
    from core.capability_registry.bootstrap import (
        reset_for_tests,
    )
    reset_for_tests()
    yield
    reset_for_tests()


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kw):
    defaults = dict(
        yes=False,
        skip_correlate=False,
        skip_advance=False,
        skip_defend=False,
        history=False,
        history_window_days=7,
        history_limit=10,
        alerts=False,
        json=False,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _fake_sm(stores=None):
    sm = MagicMock()
    sm.list_stores.return_value = stores or []
    sm.active_store_id = None
    return sm


class TestDryRun:

    def test_default_dry_run_renders_both_phases(
        self, cli,
    ):
        sm = _fake_sm([
            {"store_id": "a", "shop_url": "x"},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_autonomous_cycle, _ns(),
            )
        assert code == 0
        assert "DRY-RUN" in out
        assert "Advance:" in out
        assert "Measure:" in out
        assert "Dry-run only" in out


class TestSkipFlags:

    def test_skip_advance_only_correlate(self, cli):
        sm = _fake_sm([
            {"store_id": "a", "shop_url": "x"},
        ])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(skip_advance=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        # Advance phase skipped -> None
        assert data["advance"] is None
        # Correlate ran (empty fleet -> 0 candidates)
        assert data["correlate"] is not None

    def test_skip_correlate_only_advance(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ):
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(skip_correlate=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        # Correlate skipped
        assert data["correlate"] is None
        assert data["advance"] is not None


class TestExecuted:

    def test_yes_records_executed_True(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=True, json=True),
            )
        data = json.loads(out)
        assert data["executed"] is True


class TestDefendPhase:
    """Defend phase runs auto-demote-degraded against the
    captured plan history. Env-gated; safe by default."""

    def test_defend_dry_run_reports_zero_actionable(
        self, cli,
    ):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "config_summary",
            return_value={
                "enabled": False,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
                "recovery_threshold": 0.7,
            },
        ):
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["defend"] == {
            "gate_enabled": False,
            "candidates": 0,
            "actionable": 0,
            "demoted": 0,
            "demoted_capabilities": [],
            "recovered_candidates": 0,
            "released": 0,
            "released_capabilities": [],
        }

    def test_defend_yes_calls_apply(self, cli):
        sm = _fake_sm([])
        candidates = [
            {
                "capability": "cap_x",
                "baseline_rate": 0.9,
                "recent_rate": 0.1,
                "drop": 0.8,
                "recent_samples": 5,
                "baseline_samples": 20,
                "blocked_by": None,
            },
        ]
        applied = [{
            "capability": "cap_x",
            "drop": 0.8,
            "baseline_rate": 0.9,
            "recent_rate": 0.1,
            "recent_samples": 5,
            "baseline_samples": 20,
            "reason": "auto_demote_degraded: ...",
        }]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=candidates,
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "config_summary",
            return_value={
                "enabled": True,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
                "recovery_threshold": 0.7,
            },
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_auto_demote_degraded",
            return_value=applied,
        ) as mock_apply, patch(
            "core.capability_planner.auto_demote."
            "maybe_release_recovered",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert mock_apply.call_count == 1
        assert data["defend"]["gate_enabled"] is True
        assert data["defend"]["actionable"] == 1
        assert data["defend"]["demoted"] == 1
        assert data["defend"]["demoted_capabilities"] == [
            "cap_x",
        ]
        assert data["defend"]["released"] == 0

    def test_defend_dry_run_does_not_call_apply(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "config_summary",
            return_value={
                "enabled": True,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
                "recovery_threshold": 0.7,
            },
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_auto_demote_degraded",
        ) as mock_apply, patch(
            "core.capability_planner.auto_demote."
            "maybe_release_recovered",
        ) as mock_release:
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=False, json=True),
            )
        assert code == 0
        # Dry-run: neither apply NOR release should fire
        assert mock_apply.call_count == 0
        assert mock_release.call_count == 0

    def test_skip_defend_omits_phase(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(skip_defend=True, json=True),
            )
        assert code == 0
        data = json.loads(out)
        assert data["defend"] is None

    def test_defend_text_view_shows_demoted_capabilities(
        self, cli,
    ):
        sm = _fake_sm([])
        candidates = [{
            "capability": "cap_y",
            "baseline_rate": 0.9,
            "recent_rate": 0.1,
            "drop": 0.8,
            "recent_samples": 5,
            "baseline_samples": 20,
            "blocked_by": None,
        }]
        applied = [{
            "capability": "cap_y",
            "drop": 0.8,
            "baseline_rate": 0.9,
            "recent_rate": 0.1,
            "recent_samples": 5,
            "baseline_samples": 20,
            "reason": "auto_demote_degraded: ...",
        }]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=candidates,
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "config_summary",
            return_value={
                "enabled": True,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
                "recovery_threshold": 0.7,
            },
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_auto_demote_degraded",
            return_value=applied,
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_release_recovered",
            return_value=[],
        ):
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=True),
            )
        assert code == 0
        assert "Defend:" in out
        assert "1 demoted" in out
        assert "cap_y" in out
        assert "gate ON" in out

    def test_defend_release_text_view(self, cli):
        sm = _fake_sm([])
        release_cands = [{
            "capability": "recovered_cap",
            "recent_rate": 0.95,
            "recent_samples": 5,
            "demote_reason": "auto_demote_degraded: ...",
            "demoted_at": 100.0,
        }]
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_demote_candidates",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "find_release_candidates",
            return_value=release_cands,
        ), patch(
            "core.capability_planner.auto_demote."
            "config_summary",
            return_value={
                "enabled": True,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
                "recovery_threshold": 0.7,
            },
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_auto_demote_degraded",
            return_value=[],
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_release_recovered",
            return_value=release_cands,
        ) as mock_release:
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=True, json=True),
            )
        assert code == 0
        # Release is called even without gate-on
        assert mock_release.call_count == 1
        data = json.loads(out)
        assert data["defend"]["released"] == 1
        assert (
            data["defend"]["recovered_candidates"] == 1
        )
        assert (
            data["defend"]["released_capabilities"]
            == ["recovered_cap"]
        )


class TestCorrelatePhase:

    def test_correlate_runs_per_eligible_event(self, cli):
        import time as _t
        events = [{
            "event_id": "old",
            "timestamp": _t.time() - 86400 * 2,
            "goal": "g", "store_id": "s",
            "executed": True,
            "outcome": "executed_ok",
            "pre_stats": {"total_revenue": 100.0},
        }]
        sm = _fake_sm([])
        sm.get_stats = lambda sid: {
            "total_revenue": 150.0,
        }
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=events,
        ), patch(
            "core.capability_planner."
            "correlate_outcome_by_stats",
            return_value={
                "ok": True,
                "outcome": "revenue_up",
            },
        ) as mock_corr:
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(
                    yes=True,
                    skip_advance=True,
                    json=True,
                ),
            )
        assert code == 0
        data = json.loads(out)
        assert mock_corr.call_count == 1
        assert data["correlate"]["correlated"] == 1
        assert (
            data["correlate"]["by_outcome"]["revenue_up"]
            == 1
        )


class TestCycleHistory:
    """Cycle invocations persist to cycle_history audit log
    + ``--history`` flag inspects them."""

    def _event(self, **kw):
        from core.autonomous.cycle_history import CycleEvent
        defaults = dict(
            recorded_at=1700000000.0,
            executed=True,
            advance={
                "stores_processed": 1,
                "executed_ok": 1,
                "refused_reliability": 0,
                "errored": 0,
            },
            defend={
                "demoted": 0, "released": 0,
                "gate_enabled": False, "candidates": 0,
                "actionable": 0,
                "demoted_capabilities": [],
                "recovered_candidates": 0,
                "released_capabilities": [],
            },
            correlate={
                "candidates": 0, "correlated": 0,
                "by_outcome": {},
            },
            flags={},
        )
        defaults.update(kw)
        return CycleEvent(**defaults)

    def test_record_cycle_called_on_invocation(self, cli):
        """The cycle handler records the invocation to the
        history log after computing the summary."""
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_history.record_cycle",
        ) as mock_record:
            _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=True, json=True),
            )
        assert mock_record.call_count == 1
        # Check key kwargs forwarded
        call_kwargs = mock_record.call_args.kwargs
        assert call_kwargs["executed"] is True
        assert "advance" in call_kwargs
        assert "defend" in call_kwargs
        assert "correlate" in call_kwargs
        assert "flags" in call_kwargs

    def test_dry_run_also_records(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_history.record_cycle",
        ) as mock_record:
            _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=False, json=True),
            )
        assert mock_record.call_count == 1
        assert (
            mock_record.call_args.kwargs["executed"]
            is False
        )

    def test_history_flag_skips_cycle_run(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ) as mock_sm, patch(
            "core.autonomous.cycle_history.recent_history",
            return_value=[],
        ), patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value={
                "total_runs": 0,
                "executed_runs": 0,
                "dry_run_count": 0,
                "last_run_at": None,
                "stores_advanced_total": 0,
                "stores_refused_total": 0,
                "demoted_total": 0,
                "released_total": 0,
                "correlated_total": 0,
            },
        ):
            out, _ = _capture(
                cli._cmd_autonomous_cycle,
                _ns(history=True),
            )
            return_code = 0
        # --history is read-only; store-manager should not
        # be consulted (no cycle ran)
        mock_sm.assert_not_called()
        assert "Autonomous cycle history" in out
        assert "No recent invocations" in out

    def test_history_renders_events(self, cli):
        events = [
            self._event(
                recorded_at=1700000100.0,
                executed=True,
                advance={
                    "stores_processed": 3,
                    "executed_ok": 2,
                    "refused_reliability": 1,
                    "errored": 0,
                },
                defend={
                    "demoted": 1, "released": 0,
                    "gate_enabled": True,
                },
                correlate={"correlated": 2},
            ),
        ]
        stats = {
            "total_runs": 1, "executed_runs": 1,
            "dry_run_count": 0,
            "last_run_at": 1700000100.0,
            "stores_advanced_total": 2,
            "stores_refused_total": 1,
            "demoted_total": 1,
            "released_total": 0,
            "correlated_total": 2,
        }
        with patch(
            "core.autonomous.cycle_history.recent_history",
            return_value=events,
        ), patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=stats,
        ):
            out, _ = _capture(
                cli._cmd_autonomous_cycle,
                _ns(history=True),
            )
        assert "Autonomous cycle history" in out
        assert "Runs: 1 total" in out
        # Aggregate totals visible
        assert "2 stores advanced" in out
        assert "1 refused" in out
        assert "1 demoted" in out
        # Per-event detail rendered
        assert "[EXEC]" in out
        assert "adv=2ok/1ref" in out
        assert "def=1d/0r" in out
        assert "cor=2c" in out

    def test_history_json_envelope(self, cli):
        events = [self._event()]
        stats = {
            "total_runs": 1, "executed_runs": 1,
            "dry_run_count": 0,
            "last_run_at": 1700000000.0,
            "stores_advanced_total": 1,
            "stores_refused_total": 0,
            "demoted_total": 0,
            "released_total": 0,
            "correlated_total": 0,
        }
        with patch(
            "core.autonomous.cycle_history.recent_history",
            return_value=events,
        ), patch(
            "core.autonomous.cycle_history.cycle_stats",
            return_value=stats,
        ):
            out, _ = _capture(
                cli._cmd_autonomous_cycle,
                _ns(history=True, json=True),
            )
        data = json.loads(out)
        assert data["window_days"] == 7
        assert data["stats"]["total_runs"] == 1
        assert len(data["events"]) == 1
        assert data["events"][0]["executed"] is True


class TestNextActionInOutput:
    """The cycle handler renders a next-action recommendation
    after each run. JSON envelope carries the structured form."""

    def test_next_action_appears_in_text(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ):
            out, _ = _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=False),
            )
        assert "Next:" in out

    def test_next_action_in_json_envelope(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ), patch(
            "core.capability_planner.recent_history",
            return_value=[],
        ):
            out, _ = _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=True, json=True),
            )
        data = json.loads(out)
        assert "next_action" in data
        assert "priority" in data["next_action"]
        assert "detail" in data["next_action"]


class TestCycleAlertsFlag:
    """``shopai autonomous-cycle --alerts`` -- read-only
    cycle-health inspector."""

    def _alert(self, kind="stale_cycle", detail="d", **kw):
        from core.autonomous.cycle_alerts import CycleAlert
        return CycleAlert(kind=kind, detail=detail, metrics=kw)

    def test_alerts_flag_skips_cycle_run(self, cli):
        sm = _fake_sm([])
        with patch.object(
            cli, "_get_store_manager", return_value=sm,
        ) as mock_sm, patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=[],
        ):
            out, _ = _capture(
                cli._cmd_autonomous_cycle,
                _ns(alerts=True),
            )
        mock_sm.assert_not_called()
        assert "No alerts" in out

    def test_alerts_render_when_present(self, cli):
        alerts = [
            self._alert(
                kind="stale_cycle",
                detail="Last cycle ran 48.0h ago",
            ),
            self._alert(
                kind="low_advance_rate",
                detail="ADVANCE phase succeeded on 20%",
            ),
        ]
        with patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=alerts,
        ):
            out, _ = _capture(
                cli._cmd_autonomous_cycle,
                _ns(alerts=True),
            )
        assert "[stale_cycle]" in out
        assert "Last cycle ran" in out
        assert "[low_advance_rate]" in out
        assert "20%" in out

    def test_alerts_json_envelope(self, cli):
        alerts = [self._alert()]
        with patch(
            "core.autonomous.cycle_alerts."
            "compute_cycle_alerts",
            return_value=alerts,
        ):
            out, _ = _capture(
                cli._cmd_autonomous_cycle,
                _ns(alerts=True, json=True),
            )
        data = json.loads(out)
        assert "config" in data
        assert "alerts" in data
        assert len(data["alerts"]) == 1
        assert data["alerts"][0]["kind"] == "stale_cycle"
