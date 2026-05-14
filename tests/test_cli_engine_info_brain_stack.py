"""Tests for the brain-stack section in ``shopai engine-info``.

The base ``engine-info ENGINE`` block (name/class/inputs/outputs)
still appears unchanged. After it, the new Brain stack block
shows:
  - Primary goal (from ENGINE_GOAL_MAP)
  - Current per-goal effectiveness EMA (from GoalManager)

Unmapped engines get a single line explaining their actions don't
attribute to any goal.
"""
from __future__ import annotations

import importlib.util
from io import StringIO
from unittest.mock import patch

import pytest


def _load_cli():
    spec = importlib.util.spec_from_file_location("shopai_cli", "cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cli():
    return _load_cli()


def _capture(fn, *args, **kwargs) -> str:
    buf = StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ─── Brain-stack block on a mapped engine ─────────────────────────


class TestMappedEngine:

    def test_shows_primary_goal(self, cli):
        out = _capture(cli._cmd_engine_info, "cart_recovery")
        assert "Brain stack:" in out
        assert "Goal:" in out
        assert "grow_customers" in out

    def test_shows_default_effectiveness_when_no_outcomes(self, cli):
        """A fresh GoalManager has no recorded outcomes — surface
        the default neutral score so operators know it's not learned
        yet, rather than rendering an empty stat."""
        out = _capture(cli._cmd_engine_info, "cart_recovery")
        # Either "default" wording OR the actual EMA float — both OK
        assert "Effectiveness:" in out
        assert any(
            substr in out
            for substr in ("default", "0.50", "0.5")
        )

    def test_shows_learned_effectiveness_when_present(self, cli):
        """When GoalManager has recorded outcomes, the EMA + sample
        count surface."""
        fake_stats = {
            "grow_customers": {"ema": 0.72, "n": 14},
        }
        with patch(
            "core.goals.goal_manager.GoalManager.get_effectiveness_stats",
            return_value=fake_stats,
        ):
            out = _capture(cli._cmd_engine_info, "cart_recovery")
        assert "Effectiveness:  0.72" in out
        assert "14 recorded outcomes" in out


# ─── Brain-stack block on an unmapped engine ──────────────────────


class TestUnmappedEngine:

    def test_unmapped_explains(self, cli):
        """An engine not in ENGINE_GOAL_MAP gets a single-line
        explanation rather than a misleading 'unmapped' goal."""
        out = _capture(cli._cmd_engine_info, "cohort_analysis")
        assert "Brain stack:" in out
        assert "(unmapped" in out
        # No EMA line — the goal attribution is the prerequisite
        assert "Effectiveness:" not in out


# ─── Failure resilience ──────────────────────────────────────────


class TestResilience:

    def test_goal_manager_failure_doesnt_crash(self, cli):
        """If GoalManager raises, engine-info still completes
        (the base section comes through, brain stack truncates)."""
        with patch(
            "core.goals.goal_manager.GoalManager",
            side_effect=RuntimeError("manager broken"),
        ):
            out = _capture(cli._cmd_engine_info, "cart_recovery")
        # Base info still present
        assert "Engine: cart_recovery" in out
        # Goal line still rendered (uses static map, not manager)
        assert "Goal:           grow_customers" in out
        # No effectiveness line (manager failed)
        assert "Effectiveness:" not in out

    def test_unknown_engine_still_exits_1(self, cli):
        """Unknown engine path unchanged — exit 1 + message."""
        with pytest.raises(SystemExit) as exc:
            _capture(cli._cmd_engine_info, "definitely_not_a_real_engine_xyz")
        assert exc.value.code == 1


# ─── Base section preserved ───────────────────────────────────────


class TestBaseSectionUnchanged:

    def test_base_lines_still_present(self, cli):
        """The name/class/inputs/outputs lines all still appear —
        new section adds, doesn't replace."""
        out = _capture(cli._cmd_engine_info, "cart_recovery")
        assert "Engine: cart_recovery" in out
        assert "Class:" in out
