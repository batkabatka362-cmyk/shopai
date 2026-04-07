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


# ── think + llm-status ──────────────────────────────────────


class TestMindThink:
    def test_empty_question(self, fresh_mind, capsys):
        import cli
        cli.main(["mind", "think", " "])
        out = capsys.readouterr().out
        assert "Empty" in out or "nothing" in out

    def test_no_llm_configured(self, fresh_mind, monkeypatch, capsys):
        # Force LLM adapter to report no providers
        import cli
        from core.system import llm_adapter as la

        class _NoLLM:
            def is_available(self):
                return False

        monkeypatch.setattr(la, "get_llm", lambda: _NoLLM())
        cli.main(["mind", "think", "should I", "lower prices"])
        out = capsys.readouterr().out
        assert "No LLM providers" in out

    def test_successful_response(self, fresh_mind, monkeypatch, capsys):
        import cli
        from core.system import llm_adapter as la

        class _FakeResp:
            success = True
            error = ""
            text = "Yes, lower them by 10% on slow movers."
            provider = "ollama"
            model = "mistral"
            tokens_used = 42
            duration_s = 0.5
            fallback_used = False

        class _FakeLLM:
            def is_available(self):
                return True

            def ask(self, role="", prompt="", system_prompt="", **kw):
                return _FakeResp()

        monkeypatch.setattr(la, "get_llm", lambda: _FakeLLM())
        cli.main(["mind", "think", "should I lower prices?"])
        out = capsys.readouterr().out
        assert "Yes, lower them" in out
        assert "ollama/mistral" in out
        assert "42 tokens" in out

    def test_question_with_self_context(self, fresh_mind, monkeypatch, capsys):
        # Plant some self-knowledge so the context block fires
        for _ in range(15):
            fresh_mind.self_model.assess("engine.x", 0.2)
        fresh_mind.goal_manager.propose("Improve engine.x")

        captured = {}
        from core.system import llm_adapter as la

        class _FakeResp:
            success = True
            error = ""
            text = "ok"
            provider = "ollama"
            model = "mistral"
            tokens_used = 1
            duration_s = 0.1
            fallback_used = False

        class _FakeLLM:
            def is_available(self):
                return True

            def ask(self, role="", prompt="", system_prompt="", **kw):
                captured["prompt"] = prompt
                return _FakeResp()

        monkeypatch.setattr(la, "get_llm", lambda: _FakeLLM())
        import cli
        cli.main(["mind", "think", "what next?"])
        # Self-context block should be in the prompt
        assert "engine.x" in captured["prompt"]
        assert "Improve" in captured["prompt"]

    def test_no_context_flag_skips_self_block(self, fresh_mind, monkeypatch, capsys):
        for _ in range(15):
            fresh_mind.self_model.assess("engine.something", 0.2)

        captured = {}
        from core.system import llm_adapter as la

        class _FakeResp:
            success = True
            error = ""
            text = "ok"
            provider = "ollama"
            model = "mistral"
            tokens_used = 1
            duration_s = 0.1
            fallback_used = False

        class _FakeLLM:
            def is_available(self):
                return True

            def ask(self, role="", prompt="", system_prompt="", **kw):
                captured["prompt"] = prompt
                return _FakeResp()

        monkeypatch.setattr(la, "get_llm", lambda: _FakeLLM())
        import cli
        cli.main(["mind", "think", "--no-context", "abstract", "question"])
        assert "engine.something" not in captured["prompt"]


class TestLLMStatus:
    def test_prints_status_block(self, fresh_mind, capsys):
        import cli
        cli.main(["mind", "llm-status"])
        out = capsys.readouterr().out
        assert "LLM PROVIDER STATUS" in out
        assert "Role mapping" in out
        assert "Fallback chain" in out


# ── LLM stats embedded in `mind status` ──────────────────────


class TestMindStatusLLM:
    def test_status_shows_no_providers(self, fresh_mind, monkeypatch, capsys):
        from core.system import llm_adapter as la

        class _NoLLM:
            def get_stats(self):
                return {
                    "configured": [],
                    "available_local": [],
                    "models": {},
                    "fallback_chain": [],
                    "role_map": {},
                }

        monkeypatch.setattr(la, "get_llm", lambda: _NoLLM())
        import cli
        cli.main(["mind", "status"])
        out = capsys.readouterr().out
        assert "LLM:" in out
        assert "no providers configured" in out

    def test_status_shows_provider_and_cache(
        self, fresh_mind, monkeypatch, capsys,
    ):
        from core.system import llm_adapter as la

        class _FakeLLM:
            def get_stats(self):
                return {
                    "configured": ["mistral", "openai_main"],
                    "available_local": ["mistral"],
                    "fallback_chain": ["mistral", "openai_main"],
                    "role_map": {"reasoner": "mistral"},
                    "models": {
                        "mistral": {
                            "calls": 7, "errors": 1,
                            "tokens": 1234, "fallbacks": 2,
                            "total_time": 1.0,
                        },
                        "openai_main": {
                            "calls": 3, "errors": 0,
                            "tokens": 500, "fallbacks": 0,
                            "total_time": 0.5,
                        },
                    },
                }

        monkeypatch.setattr(la, "get_llm", lambda: _FakeLLM())

        # Warm cache so we get non-zero stats
        from core.system.llm_cache import get_llm_cache

        class _Resp:
            success = True

        cache = get_llm_cache()
        cache.put("reasoner", "p", "", _Resp(), model="mistral")
        cache.get("reasoner", "p", "", model="mistral")  # 1 hit
        cache.get("reasoner", "missing", "", model="mistral")  # 1 miss

        import cli
        cli.main(["mind", "status"])
        out = capsys.readouterr().out
        assert "LLM:" in out
        assert "providers=2" in out
        assert "local=1" in out
        assert "calls=10" in out
        assert "errors=1" in out
        assert "tokens=1734" in out
        assert "fallbacks_used=2" in out
        assert "cache:" in out
        assert "hits=" in out
        assert "hit_rate=" in out

    def test_status_handles_llm_exception(
        self, fresh_mind, monkeypatch, capsys,
    ):
        from core.system import llm_adapter as la

        def _boom():
            raise RuntimeError("adapter exploded")

        monkeypatch.setattr(la, "get_llm", _boom)
        import cli
        cli.main(["mind", "status"])
        out = capsys.readouterr().out
        assert "LLM: unavailable" in out
        assert "adapter exploded" in out
