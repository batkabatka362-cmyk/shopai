"""Tests for AutonomousController ↔ Mind integration."""
import tempfile

import pytest


def _real_mind():
    """Build a real cognitive Mind with all 9 modules wired."""
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

    return Mind(
        self_model=sm,
        goal_manager=gm,
        reflection=Reflection(memory=mem, self_model=sm,
                              goal_manager=gm, use_llm=False),
        planner=Planner(backends=[HeuristicPlanBackend()]),
        imagination=Imagination(self_model=sm, memory=mem, use_llm=False),
        curiosity=Curiosity(self_model=sm, goal_manager=gm,
                            rng_seed=1, use_llm=False),
        consolidation=Consolidation(memory=mem),
        skill_registry=SkillRegistry(),
        theory_of_mind=tom,
        memory=mem,
    )


# ── Constructor + mode ──────────────────────────────────────


class TestConstruction:
    def test_default_mode_off(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController()
        assert c.cognitive_mode == "off"

    def test_explicit_off(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController(cognitive_mind=_real_mind(), cognitive_mode="off")
        assert c.cognitive_mode == "off"

    def test_shadow_mode(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController(cognitive_mind=_real_mind(), cognitive_mode="shadow")
        assert c.cognitive_mode == "shadow"

    def test_primary_mode(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController(cognitive_mind=_real_mind(), cognitive_mode="primary")
        assert c.cognitive_mode == "primary"

    def test_invalid_mode_falls_back_to_off(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController(cognitive_mind=_real_mind(), cognitive_mode="alien")
        assert c.cognitive_mode == "off"


# ── attach_cognitive_mind ───────────────────────────────────


class TestAttach:
    def test_attach_after_construction(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController()
        assert c.cognitive_mode == "off"
        c.attach_cognitive_mind(_real_mind(), mode="shadow")
        assert c.cognitive_mode == "shadow"
        assert c._cognitive_mind is not None

    def test_attach_invalid_mode_keeps_default(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController()
        c.attach_cognitive_mind(_real_mind(), mode="invalid")
        assert c.cognitive_mode == "off"


# ── run_cognitive_cycle (standalone) ────────────────────────


class TestStandaloneCognitive:
    def test_returns_error_when_no_mind(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController()
        result = c.run_cognitive_cycle()
        assert "error" in result
        assert "no cognitive Mind" in result["error"]

    def test_returns_report_when_mind_wired(self):
        from core.autonomous.controller import AutonomousController
        mind = _real_mind()
        c = AutonomousController(cognitive_mind=mind)
        result = c.run_cognitive_cycle()
        # CycleReport.to_dict always includes 'error' (empty string
        # on success) — that's success, not failure
        assert not result.get("error")
        assert "cycle_number" in result
        assert result["cycle_number"] == 1

    def test_increments_cycle_counter(self):
        from core.autonomous.controller import AutonomousController
        mind = _real_mind()
        c = AutonomousController(cognitive_mind=mind)
        r1 = c.run_cognitive_cycle()
        r2 = c.run_cognitive_cycle()
        assert r1["cycle_number"] == 1
        assert r2["cycle_number"] == 2


# ── _run_cognitive_phase (called from run_cycle) ────────────


class TestPhaseHook:
    def test_no_mind_no_phase(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController()
        result = c._run_cognitive_phase({"cycle_id": "cyc_1"})
        assert result is None

    def test_with_mind_returns_dict(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController(cognitive_mind=_real_mind(), cognitive_mode="shadow")
        result = c._run_cognitive_phase({
            "cycle_id": "cyc_1",
            "store_id": "test",
            "phases": {"data": {}, "analyze": {}},
        })
        assert isinstance(result, dict)
        assert "cycle_number" in result

    def test_mind_failure_caught(self):
        from core.autonomous.controller import AutonomousController

        class BrokenMind:
            def run_cycle(self, inputs=None):
                raise RuntimeError("oops")

        c = AutonomousController(cognitive_mind=BrokenMind(), cognitive_mode="shadow")
        result = c._run_cognitive_phase({"cycle_id": "x"})
        assert result is not None
        assert "error" in result

    def test_inputs_passed_to_mind(self):
        from core.autonomous.controller import AutonomousController
        captured = {}

        class SpyMind:
            def run_cycle(self, inputs=None):
                captured["inputs"] = inputs

                class _R:
                    def to_dict(self):
                        return {"cycle_number": 1}

                return _R()

        c = AutonomousController(cognitive_mind=SpyMind(), cognitive_mode="shadow")
        c._run_cognitive_phase({
            "cycle_id": "cyc_42",
            "store_id": "store_x",
            "phases": {"data": {}, "decide": {}},
        })
        assert captured["inputs"]["legacy_cycle_id"] == "cyc_42"
        assert captured["inputs"]["store_id"] == "store_x"
        assert "data" in captured["inputs"]["phases_summary"]


# ── Backwards compatibility ─────────────────────────────────


class TestBackwardsCompat:
    def test_legacy_constructor_still_works(self):
        from core.autonomous.controller import AutonomousController
        # Original 2-arg signature
        c = AutonomousController(store_manager=None, auto_approve=False)
        assert c.cognitive_mode == "off"
        assert c._cognitive_mind is None

    def test_no_cognitive_means_no_cognitive_key(self):
        """When mode is off, cycle_result must NOT contain a 'cognitive'
        key — backwards compat with anything reading the result dict."""
        from core.autonomous.controller import AutonomousController
        c = AutonomousController()
        # Manually call _run_cognitive_phase to verify the gate
        out = c._run_cognitive_phase({"cycle_id": "x"})
        assert out is None


# ── Initialization failure surfaces (audit fix #3) ────────────


class TestInitializationFailureSurfaces:
    """Regression: bare `except Exception: pass` previously hid all
    init failures behind a successful "initialized" log line. The
    operator had no idea memory/LLM/dispatchers had failed to load."""

    def test_init_failure_returns_degraded_status(self, monkeypatch):
        from core.autonomous.controller import AutonomousController
        import core.memory.unified_memory as um

        def _boom():
            raise RuntimeError("memory backend on fire")

        monkeypatch.setattr(um, "get_unified_memory", _boom)

        c = AutonomousController()
        result = c.initialize()
        assert result["status"] == "degraded"
        assert "memory backend on fire" in result["error"]
        assert "RuntimeError" in result["error"]

    def test_init_failure_records_error_on_instance(self, monkeypatch):
        from core.autonomous.controller import AutonomousController
        import core.memory.unified_memory as um

        monkeypatch.setattr(
            um, "get_unified_memory",
            lambda: (_ for _ in ()).throw(ValueError("nope")),
        )
        c = AutonomousController()
        c.initialize()
        assert c._init_error
        assert "ValueError" in c._init_error
        assert c._unified_memory is None
        assert c._layer_dispatcher is None
        assert c._agent_dispatcher is None

    def test_init_success_clears_error(self):
        from core.autonomous.controller import AutonomousController
        c = AutonomousController()
        result = c.initialize()
        # Real init may succeed or fail depending on env, but the
        # contract is: status is one of {"initialized", "degraded"}
        # and _init_error matches.
        assert result["status"] in ("initialized", "degraded")
        if result["status"] == "initialized":
            assert c._init_error == ""
        else:
            assert c._init_error
