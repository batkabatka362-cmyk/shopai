"""Tests for the `shopai mind` CLI commands."""
import os
import tempfile

import pytest


@pytest.fixture
def fresh_mind(monkeypatch):
    """Replace the cli's get_mind() with a fresh wired Mind so the
    test starts from a clean slate."""
    from core.cognitive.consolidation import Consolidation
    from core.cognitive.curiosity import Curiosity
    from core.cognitive.goals import GoalManager
    from core.cognitive.imagination import Imagination
    from core.cognitive.mind import Mind
    from core.cognitive.planner import HeuristicPlanBackend, Planner
    from core.cognitive.reflection import Reflection
    from core.cognitive.self_model import SelfModel
    from core.cognitive.skill_registry import SkillRegistry
    from core.cognitive.theory_of_mind import TheoryOfMind
    from core.memory.intelligence import MemoryIntelligence

    sm = SelfModel(db_path=tempfile.mktemp(suffix=".db"))
    gm = GoalManager(db_path=tempfile.mktemp(suffix=".db"))
    mem = MemoryIntelligence(db_path=tempfile.mktemp(suffix=".db"))
    tom = TheoryOfMind(db_path=tempfile.mktemp(suffix=".db"))

    mind = Mind(
        self_model=sm,
        goal_manager=gm,
        reflection=Reflection(memory=mem, self_model=sm, goal_manager=gm),
        planner=Planner(backends=[HeuristicPlanBackend()]),
        imagination=Imagination(self_model=sm, memory=mem),
        curiosity=Curiosity(self_model=sm, goal_manager=gm, rng_seed=1),
        consolidation=Consolidation(memory=mem),
        skill_registry=SkillRegistry(),
        theory_of_mind=tom,
        memory=mem,
    )

    import cli
    monkeypatch.setattr(cli, "_get_mind", lambda: mind)
    monkeypatch.setenv("SHOPAI_SKIP_CONFIG_CHECK", "1")
    return mind


# ── status ───────────────────────────────────────────────────


class TestMindStatus:
    def test_empty_status(self, fresh_mind, capsys):
        import cli
        cli.main(["mind", "status"])
        out = capsys.readouterr().out
        assert "COGNITIVE MIND" in out
        assert "no data about myself" in out
        assert "Active goals (0)" in out
        assert "Total cycles run: 0" in out

    def test_status_with_state(self, fresh_mind, capsys):
        # Seed weakness + goal
        for _ in range(15):
            fresh_mind.self_model.assess("engine.x", 0.2)
        fresh_mind.goal_manager.propose("Test goal", urgency=0.5)

        import cli
        cli.main(["mind", "status"])
        out = capsys.readouterr().out
        assert "engine.x" in out
        assert "weakness" in out.lower()
        assert "Test goal" in out


# ── cycle ────────────────────────────────────────────────────


class TestMindCycle:
    def test_runs_one_cycle(self, fresh_mind, capsys):
        import cli
        cli.main(["mind", "cycle"])
        out = capsys.readouterr().out
        assert "CYCLE 1" in out
        assert fresh_mind.cycle_count() == 1

    def test_cycle_with_weakness(self, fresh_mind, capsys):
        for _ in range(15):
            fresh_mind.self_model.assess("engine.broken", 0.2)
        import cli
        cli.main(["mind", "cycle"])
        out = capsys.readouterr().out
        # Should show the goal + plan + imagined output
        assert "engine.broken" in out
        assert "Plan" in out
        assert "Imagined" in out


# ── reflect ──────────────────────────────────────────────────


class TestMindReflect:
    def test_reflect_with_no_episodes(self, fresh_mind, capsys):
        import cli
        cli.main(["mind", "reflect"])
        out = capsys.readouterr().out
        assert "episodes reviewed:" in out
        assert "no episodes" in out.lower() or "lessons:" in out


# ── goals ────────────────────────────────────────────────────


class TestMindGoals:
    def test_no_goals(self, fresh_mind, capsys):
        import cli
        cli.main(["mind", "goals"])
        out = capsys.readouterr().out
        assert "No active goals" in out

    def test_lists_active_goals(self, fresh_mind, capsys):
        fresh_mind.goal_manager.propose("Goal A", urgency=0.7)
        fresh_mind.goal_manager.propose("Goal B", urgency=0.3)
        import cli
        cli.main(["mind", "goals"])
        out = capsys.readouterr().out
        assert "Goal A" in out
        assert "Goal B" in out
        assert "Total: 2" in out


# ── skills ───────────────────────────────────────────────────


class TestMindSkills:
    def test_no_skills(self, fresh_mind, capsys):
        import cli
        cli.main(["mind", "skills"])
        out = capsys.readouterr().out
        assert "No skills registered" in out

    def test_lists_skills(self, fresh_mind, capsys):
        fresh_mind.skill_registry.propose(
            "audit", lambda i: {"status": "ok"},
        )
        fresh_mind.skill_registry.validate(
            "audit", [{"input": {}}], min_accuracy=0.5,
        )
        import cli
        cli.main(["mind", "skills"])
        out = capsys.readouterr().out
        assert "audit" in out
        assert "validated" in out


# ── explain ──────────────────────────────────────────────────


class TestMindExplain:
    def test_explain_unknown_goal(self, fresh_mind, capsys):
        import cli
        cli.main(["mind", "explain", "ghost"])
        out = capsys.readouterr().out
        assert "not found" in out

    def test_explain_real_goal(self, fresh_mind, capsys):
        gid = fresh_mind.goal_manager.propose(
            "Improve weak capability 'engine.X'",
            why="testing",
            source="self_model.weakness:engine.X",
            urgency=0.7,
        )
        import cli
        cli.main(["mind", "explain", gid])
        out = capsys.readouterr().out
        assert "GOAL" in out
        assert "engine.X" in out
        assert "Plan" in out
        assert "Imagined" in out


# ── Help / dispatch ──────────────────────────────────────────


class TestDispatch:
    def test_no_action_prints_usage(self, fresh_mind, capsys):
        import cli
        cli.main(["mind"])
        out = capsys.readouterr().out
        assert "Usage" in out
        assert "status" in out
