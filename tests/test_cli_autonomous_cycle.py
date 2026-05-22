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
            "config_summary",
            return_value={
                "enabled": False,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
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
            "config_summary",
            return_value={
                "enabled": True,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
            },
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_auto_demote_degraded",
            return_value=applied,
        ) as mock_apply:
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
            "config_summary",
            return_value={
                "enabled": True,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
            },
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_auto_demote_degraded",
        ) as mock_apply:
            out, code = _capture(
                cli._cmd_autonomous_cycle,
                _ns(yes=False, json=True),
            )
        assert code == 0
        # Dry-run: apply must NOT be called
        assert mock_apply.call_count == 0

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
            "config_summary",
            return_value={
                "enabled": True,
                "drop_threshold": 0.4,
                "min_recent_sample": 3,
                "recent_window_days": 7,
                "baseline_window_days": 30,
            },
        ), patch(
            "core.capability_planner.auto_demote."
            "maybe_auto_demote_degraded",
            return_value=applied,
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
