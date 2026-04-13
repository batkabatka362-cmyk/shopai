"""Tests for the cognitive Planner."""
import tempfile

import pytest


# ── Helpers ───────────────────────────────────────────────────


class FakeLLMResponse:
    def __init__(self, text="", success=True, error=""):
        self.text = text
        self.success = success
        self.error = error


class FakeLLM:
    """Minimal LLMAdapter-compatible fake."""

    def __init__(self, response_text="", *, success=True, raise_on_ask=False):
        self._text = response_text
        self._success = success
        self._raise = raise_on_ask
        self.calls: list[dict] = []

    def ask(self, role="", prompt="", context=None, system_prompt=""):
        self.calls.append({
            "role": role,
            "prompt": prompt,
            "context": context,
            "system_prompt": system_prompt,
        })
        if self._raise:
            raise RuntimeError("LLM crashed")
        return FakeLLMResponse(self._text, success=self._success)


def _real_goal_manager():
    from core.cognitive.goals import GoalManager
    return GoalManager(db_path=tempfile.mktemp(suffix=".db"))


# ── PlanStep / Plan dataclasses ───────────────────────────────


class TestDataclasses:
    def test_step_to_dict(self):
        from core.cognitive.planner import PlanStep
        s = PlanStep(
            description="d", rationale="r", expected_outcome="e",
            estimated_cost=0.4, estimated_impact=0.7, confidence=0.8,
        )
        d = s.to_dict()
        assert d["description"] == "d"
        assert d["estimated_cost"] == 0.4
        assert d["sub_steps"] == []

    def test_plan_is_empty_and_step_count(self):
        from core.cognitive.planner import Plan, PlanStep
        p = Plan(goal_id="", goal_what="x")
        assert p.is_empty()
        assert p.step_count() == 0
        p.steps.append(PlanStep(description="a"))
        assert not p.is_empty()
        assert p.step_count() == 1


# ── HeuristicPlanBackend ──────────────────────────────────────


class TestHeuristicBackend:
    def _backend(self):
        from core.cognitive.planner import HeuristicPlanBackend
        return HeuristicPlanBackend()

    def test_improve_pattern(self):
        plan = self._backend().decompose("Improve weak capability 'engine.pricing'")
        assert plan.backend == "heuristic"
        assert len(plan.steps) >= 4
        # Target should be substituted into step descriptions
        assert any("engine.pricing" in s.description for s in plan.steps)

    def test_explore_pattern(self):
        plan = self._backend().decompose("Explore unknown capability 'engine.mystery'")
        assert len(plan.steps) >= 3
        assert any("mystery" in s.description for s in plan.steps)
        # First step should be a survey
        assert "Survey" in plan.steps[0].description or "data" in plan.steps[0].description

    def test_recover_pattern(self):
        plan = self._backend().decompose("Recover revenue")
        assert any(
            "known-good" in s.description or "rollback" in s.description.lower()
            for s in plan.steps
        )

    def test_increase_pattern(self):
        plan = self._backend().decompose("Increase conversion rate")
        descriptions = " ".join(s.description for s in plan.steps)
        assert "baseline" in descriptions.lower() or "experiment" in descriptions.lower()

    def test_decrease_pattern(self):
        plan = self._backend().decompose("Reduce cart abandonment")
        descriptions = " ".join(s.description for s in plan.steps)
        assert "baseline" in descriptions.lower() or "source" in descriptions.lower()

    def test_unknown_goal_falls_back_to_default(self):
        plan = self._backend().decompose("do a thing nobody planned for")
        assert len(plan.steps) >= 3  # default template has 5 steps

    def test_confidence_is_set(self):
        plan = self._backend().decompose("Improve X")
        for s in plan.steps:
            assert 0.0 <= s.confidence <= 1.0

    def test_case_insensitive_match(self):
        plan_lower = self._backend().decompose("improve x")
        plan_upper = self._backend().decompose("IMPROVE X")
        assert len(plan_lower.steps) == len(plan_upper.steps)


# ── LLMPlanBackend ────────────────────────────────────────────


class TestLLMBackend:
    def _backend(self, llm):
        from core.cognitive.planner import LLMPlanBackend
        return LLMPlanBackend(llm=llm)

    def test_parses_clean_json(self):
        llm = FakeLLM(response_text="""
        {"steps": [
            {"description": "step 1", "rationale": "r1", "estimated_cost": 0.2, "estimated_impact": 0.8, "confidence": 0.9},
            {"description": "step 2", "rationale": "r2"},
            {"description": "step 3"}
        ]}
        """)
        plan = self._backend(llm).decompose("improve X")
        assert plan.backend == "llm"
        assert len(plan.steps) == 3
        assert plan.steps[0].description == "step 1"
        assert plan.steps[0].estimated_cost == 0.2
        assert plan.steps[0].confidence == 0.9
        assert plan.steps[1].description == "step 2"
        # Defaults filled in for step 3
        assert plan.steps[2].confidence == 0.5

    def test_strips_markdown_code_fence(self):
        llm = FakeLLM(response_text="""```json
        {"steps": [{"description": "do it"}]}
        ```""")
        plan = self._backend(llm).decompose("X")
        assert len(plan.steps) == 1
        assert plan.steps[0].description == "do it"

    def test_extracts_json_from_chatter(self):
        llm = FakeLLM(response_text="""
        Sure! Here's a plan:
        {"steps": [{"description": "first thing"}, {"description": "second thing"}]}
        Let me know if you want me to elaborate.
        """)
        plan = self._backend(llm).decompose("X")
        assert len(plan.steps) == 2

    def test_invalid_json_returns_empty_plan(self):
        llm = FakeLLM(response_text="not json at all")
        plan = self._backend(llm).decompose("X")
        assert plan.is_empty()

    def test_no_steps_array_returns_empty(self):
        llm = FakeLLM(response_text='{"hello": "world"}')
        plan = self._backend(llm).decompose("X")
        assert plan.is_empty()

    def test_failed_response_returns_empty(self):
        llm = FakeLLM(response_text="", success=False)
        plan = self._backend(llm).decompose("X")
        assert plan.is_empty()

    def test_llm_exception_returns_empty(self):
        llm = FakeLLM(raise_on_ask=True)
        plan = self._backend(llm).decompose("X")
        assert plan.is_empty()

    def test_step_count_capped_at_10(self):
        steps = [{"description": f"s{i}"} for i in range(20)]
        llm = FakeLLM(response_text='{"steps": ' + str(steps).replace("'", '"') + '}')
        plan = self._backend(llm).decompose("X")
        assert len(plan.steps) <= 10

    def test_skips_step_without_description(self):
        llm = FakeLLM(response_text='{"steps": [{"description": "ok"}, {"rationale": "no desc"}, {}]}')
        plan = self._backend(llm).decompose("X")
        assert len(plan.steps) == 1

    def test_clamps_out_of_range_floats(self):
        llm = FakeLLM(response_text="""
        {"steps": [{"description": "x", "estimated_cost": 1.5, "confidence": -0.3}]}
        """)
        plan = self._backend(llm).decompose("X")
        s = plan.steps[0]
        assert s.estimated_cost == 1.0
        assert s.confidence == 0.0

    def test_non_numeric_floats_default(self):
        llm = FakeLLM(response_text="""
        {"steps": [{"description": "x", "estimated_cost": "high"}]}
        """)
        plan = self._backend(llm).decompose("X")
        assert plan.steps[0].estimated_cost == 0.5

    def test_passes_system_prompt_and_context(self):
        llm = FakeLLM(response_text='{"steps": [{"description": "x"}]}')
        self._backend(llm).decompose("X", context={"recent": "data"})
        call = llm.calls[0]
        assert "planning assistant" in call["system_prompt"]
        assert call["context"] == {"recent": "data"}
        assert call["role"] == "analyzer"


# ── Top-level Planner ─────────────────────────────────────────


class TestPlanner:
    def _planner(self, *, llm_text="", llm_success=True):
        from core.cognitive.planner import (
            Planner, LLMPlanBackend, HeuristicPlanBackend,
        )
        llm_backend = LLMPlanBackend(
            llm=FakeLLM(response_text=llm_text, success=llm_success),
        )
        return Planner(backends=[llm_backend, HeuristicPlanBackend()])

    def test_uses_llm_when_available(self):
        p = self._planner(llm_text='{"steps": [{"description": "from LLM"}]}')
        plan = p.plan("Improve X")
        assert plan.backend == "llm"
        assert plan.steps[0].description == "from LLM"

    def test_falls_back_to_heuristic_when_llm_fails(self):
        p = self._planner(llm_text="garbage not json")
        plan = p.plan("Improve weak capability 'engine.x'")
        assert plan.backend == "heuristic"
        assert len(plan.steps) >= 3

    def test_falls_back_when_llm_returns_failure(self):
        p = self._planner(llm_text="", llm_success=False)
        plan = p.plan("Improve X")
        assert plan.backend == "heuristic"

    def test_empty_goal_returns_empty_plan(self):
        p = self._planner(llm_text='{"steps": [{"description": "x"}]}')
        plan = p.plan("")
        assert plan.is_empty()
        assert plan.backend == "empty"

    def test_accepts_dict_goal(self):
        p = self._planner(llm_text='{"steps": [{"description": "x"}]}')
        plan = p.plan({"id": "g123", "what": "Improve X"})
        assert plan.goal_id == "g123"
        assert plan.steps[0].description == "x"

    def test_no_backend_succeeds_returns_none_backend(self):
        from core.cognitive.planner import Planner
        # Empty backend list → no plan possible
        plan = Planner(backends=[]).plan("Improve X")
        assert plan.is_empty()
        assert plan.backend == "none"

    def test_backend_exception_falls_through(self):
        from core.cognitive.planner import (
            Planner, HeuristicPlanBackend, PlanBackend, Plan,
        )

        class CrashingBackend(PlanBackend):
            name = "crash"

            def decompose(self, goal_what, *, context=None):
                raise RuntimeError("boom")

        p = Planner(backends=[CrashingBackend(), HeuristicPlanBackend()])
        plan = p.plan("Improve weak X")
        assert plan.backend == "heuristic"
        assert not plan.is_empty()


class TestReplan:
    def _planner(self):
        from core.cognitive.planner import Planner, HeuristicPlanBackend
        return Planner(backends=[HeuristicPlanBackend()])

    def test_replan_replaces_failing_step(self):
        from core.cognitive.planner import Plan, PlanStep
        p = self._planner()
        original = Plan(
            goal_id="g1",
            goal_what="Improve X",
            backend="heuristic",
            steps=[
                PlanStep(description="step a"),
                PlanStep(description="Improve weak Y"),  # this is the failing step
                PlanStep(description="step c"),
            ],
        )
        new_plan = p.replan(original, failed_step_index=1, evidence="Y was busy")
        # Step a should still be there
        assert new_plan.steps[0].description == "step a"
        # Step c should still be at the end
        assert new_plan.steps[-1].description == "step c"
        # In between, we should have re-planned steps (more than 1)
        assert len(new_plan.steps) > 3
        assert new_plan.backend.endswith("replan")

    def test_replan_invalid_index_returns_original(self):
        from core.cognitive.planner import Plan, PlanStep
        p = self._planner()
        original = Plan(goal_id="g", goal_what="X", steps=[PlanStep(description="a")])
        out = p.replan(original, failed_step_index=99)
        assert out is original

    def test_replan_empty_plan_returns_original(self):
        from core.cognitive.planner import Plan
        p = self._planner()
        original = Plan(goal_id="g", goal_what="X")
        out = p.replan(original, failed_step_index=0)
        assert out is original


class TestStorePlan:
    def test_persists_steps_as_child_goals(self):
        from core.cognitive.planner import Planner, HeuristicPlanBackend
        gm = _real_goal_manager()
        parent = gm.propose("Improve weak capability 'engine.X'")

        p = Planner(backends=[HeuristicPlanBackend()])
        plan = p.plan(gm.get(parent))
        ids = p.store_plan(plan, gm)
        assert len(ids) == len(plan.steps) >= 3

        children = gm.children(parent)
        assert len(children) == len(ids)
        # Each child has the parent_id set
        for c in children:
            assert c["parent_id"] == parent
            assert c["source"].startswith("planner.")

    def test_no_goal_id_means_no_persistence(self):
        from core.cognitive.planner import Planner, HeuristicPlanBackend, Plan, PlanStep
        gm = _real_goal_manager()
        plan = Plan(goal_id="", goal_what="X", steps=[PlanStep(description="a")])
        ids = Planner(backends=[HeuristicPlanBackend()]).store_plan(plan, gm)
        assert ids == []

    def test_no_goal_manager_means_empty(self):
        from core.cognitive.planner import Planner, HeuristicPlanBackend, Plan, PlanStep
        plan = Plan(goal_id="g1", goal_what="X", steps=[PlanStep(description="a")])
        ids = Planner(backends=[HeuristicPlanBackend()]).store_plan(plan, None)
        assert ids == []


class TestEndToEnd:
    def test_goal_to_plan_to_persisted_subgoals(self):
        """Full pipeline: GoalManager goal → Planner → child goals."""
        from core.cognitive.planner import Planner, HeuristicPlanBackend
        gm = _real_goal_manager()
        gid = gm.propose("Improve weak capability 'engine.flaky'", urgency=0.7)
        parent = gm.get(gid)

        planner = Planner(backends=[HeuristicPlanBackend()])
        plan = planner.plan(parent)
        assert plan.step_count() >= 4
        # Each step references the target capability
        descriptions = " ".join(s.description for s in plan.steps)
        assert "engine.flaky" in descriptions

        # Persist as children
        child_ids = planner.store_plan(plan, gm)
        assert len(child_ids) == plan.step_count()

        # Children inherit confidence from steps and have priorities
        for cid in child_ids:
            c = gm.get(cid)
            assert c["parent_id"] == gid
            assert 0 <= c["priority"] <= 1


class TestSingleton:
    def test_get_planner_cached(self):
        from core.cognitive import planner as mod
        mod._instance = None
        a = mod.get_planner()
        b = mod.get_planner()
        assert a is b
