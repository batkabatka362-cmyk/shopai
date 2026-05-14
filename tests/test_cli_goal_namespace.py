"""Tests for the ``shopai goal`` CLI namespace.

The brain-stack GoalManager has a persistent EMA store
(``data/goal_state.json``, PR #118). Operators need a way to
inspect that state without writing Python, and to reset it after
a major change (e.g., new pricing strategy that invalidates
old learned signal).

  shopai goal show       → current goal + per-goal EMA
  shopai goal reset --yes → clear EMA state
"""
from __future__ import annotations

import argparse
import importlib.util
from io import StringIO
from pathlib import Path
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


def _capture(fn, *args, **kwargs):
    buf = StringIO()
    code = 0
    try:
        with patch("sys.stdout", buf):
            fn(*args, **kwargs)
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
    return buf.getvalue(), code


def _ns(**kwargs):
    return argparse.Namespace(**kwargs)


# ─── shopai goal (no subcommand) ──────────────────────────────────


class TestGoalDispatcher:

    def test_no_subcommand_shows_usage(self, cli):
        out, code = _capture(
            cli._cmd_goal, _ns(goal_action=None),
        )
        assert code == 1
        assert "Usage:" in out
        assert "shopai goal show" in out
        assert "shopai goal reset" in out


# ─── shopai goal show ─────────────────────────────────────────────


class TestGoalShow:

    def test_no_stats_default_message(self, cli):
        mock_mgr = MagicMock()
        mock_mgr.get_current_goal.return_value = "maximize_profit"
        mock_mgr.get_effectiveness_stats.return_value = {}
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=mock_mgr,
        ):
            out, code = _capture(cli._cmd_goal_show)
        assert code == 0
        assert "Current goal:   maximize_profit" in out
        assert "no recorded outcomes yet" in out

    def test_stats_render_sorted_by_ema(self, cli):
        """Goals render highest-EMA-first so the most-effective
        ones are at the top of the table."""
        mock_mgr = MagicMock()
        mock_mgr.get_current_goal.return_value = "grow_customers"
        mock_mgr.get_effectiveness_stats.return_value = {
            "maximize_profit": {"effectiveness": 0.45, "n": 8},
            "grow_customers": {"effectiveness": 0.82, "n": 14},
            "increase_aov": {"effectiveness": 0.61, "n": 3},
        }
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=mock_mgr,
        ):
            out, code = _capture(cli._cmd_goal_show)
        assert code == 0
        # All three present
        for g in ("maximize_profit", "grow_customers", "increase_aov"):
            assert g in out
        # Sorted: grow_customers (0.82) before increase_aov (0.61)
        # before maximize_profit (0.45)
        lines = out.splitlines()
        grow_idx = next(
            i for i, l in enumerate(lines) if "grow_customers" in l
        )
        aov_idx = next(
            i for i, l in enumerate(lines) if "increase_aov" in l
        )
        profit_idx = next(
            i for i, l in enumerate(lines) if "maximize_profit" in l
        )
        assert grow_idx < aov_idx < profit_idx

    def test_no_manager_exits_1(self, cli):
        with patch(
            "core.goals.goal_feedback._default_manager",
            return_value=None,
        ):
            out, code = _capture(cli._cmd_goal_show)
        assert code == 1
        assert "Goal manager not configured" in out


# ─── shopai goal reset ────────────────────────────────────────────


class TestGoalReset:

    def test_requires_yes_flag(self, cli):
        out, code = _capture(
            cli._cmd_goal_reset, _ns(yes=False),
        )
        assert code == 1
        assert "Re-run with --yes" in out

    def test_yes_clears_stats(self, cli, tmp_path, monkeypatch):
        """With --yes: in-memory stats wiped and the on-disk state
        file removed."""
        # Build a real manager with persisted state
        state = tmp_path / "goal_state.json"
        # Disable the pytest gate so the real file gets written
        with patch(
            "core.goals.goal_manager._is_test_environment",
            return_value=False,
        ):
            from core.goals.goal_manager import GoalManager
            mgr = GoalManager(state_path=state)
            mgr.record_goal_outcome(
                "grow_customers", {"health_delta": 1.0},
            )
            assert state.exists()
            assert mgr.get_effectiveness_stats()

            # Pin the manager + default path
            monkeypatch.setattr(
                "core.goals.goal_feedback._default_manager",
                lambda: mgr,
            )
            monkeypatch.setattr(
                "core.goals.goal_manager._DEFAULT_STATE_PATH",
                state,
            )

            _capture(cli._cmd_goal_reset, _ns(yes=True))

        # In-memory cleared
        assert mgr.get_effectiveness_stats() == {}
        # File removed
        assert not state.exists()

    def test_yes_without_existing_state(self, cli, monkeypatch, tmp_path):
        """Reset with no prior state file still works — clears
        in-memory state and prints success."""
        mock_mgr = MagicMock()
        mock_mgr._lock = MagicMock()
        mock_mgr._lock.__enter__ = MagicMock(return_value=None)
        mock_mgr._lock.__exit__ = MagicMock(return_value=None)
        mock_mgr._goal_stats = {}
        monkeypatch.setattr(
            "core.goals.goal_feedback._default_manager",
            lambda: mock_mgr,
        )
        nonexistent = tmp_path / "nope.json"
        monkeypatch.setattr(
            "core.goals.goal_manager._DEFAULT_STATE_PATH",
            nonexistent,
        )

        out, code = _capture(cli._cmd_goal_reset, _ns(yes=True))
        assert code == 0
        assert "Per-goal EMA stats cleared" in out
