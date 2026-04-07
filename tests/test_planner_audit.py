"""Tests for audit-pass-26 fixes in core/cognitive/planner.

  1. _parse_steps used `re.search(r"\\{.*\\}", text, re.DOTALL)`
     which is GREEDY — it matched from the first `{` all the way
     to the LAST `}` in the response. When an LLM emitted multiple
     JSON-looking blocks (or trailing chatter with braces), the
     resulting substring was syntactically broken JSON and the
     plan came back empty.
  2. replan() spliced an empty list into the merged plan when the
     re-plan produced no steps, which removed the failed step
     entirely instead of replacing it. The owner of the plan then
     thought the failure had been recovered when in fact the
     step was just gone.
"""
import json

import pytest


# ── _parse_steps balanced JSON extraction ───────────────────


class TestParseStepsBalancedJSON:
    def test_first_balanced_object_picked_when_trailing_chatter(self):
        """Regression: previously this returned [] because the
        greedy regex grabbed from the opening brace through the
        trailing brace in the chatter, producing invalid JSON."""
        from core.cognitive.planner import LLMPlanBackend
        text = (
            '{"steps":[{"description":"step one"},{"description":"step two"}]}'
            '\n\nNote: this is some trailing thought {with braces} blah'
        )
        steps = LLMPlanBackend._parse_steps(text)
        assert len(steps) == 2
        assert steps[0].description == "step one"
        assert steps[1].description == "step two"

    def test_first_object_when_two_json_blocks(self):
        from core.cognitive.planner import LLMPlanBackend
        text = (
            '{"steps":[{"description":"first"}]}\n'
            '{"steps":[{"description":"second"}]}'
        )
        steps = LLMPlanBackend._parse_steps(text)
        assert len(steps) == 1
        assert steps[0].description == "first"

    def test_strips_code_fence(self):
        from core.cognitive.planner import LLMPlanBackend
        text = (
            "```json\n"
            '{"steps":[{"description":"only step"}]}\n'
            "```"
        )
        steps = LLMPlanBackend._parse_steps(text)
        assert len(steps) == 1
        assert steps[0].description == "only step"

    def test_handles_nested_braces_in_string(self):
        """A string field containing braces should not confuse
        the brace counter."""
        from core.cognitive.planner import LLMPlanBackend
        text = (
            '{"steps":[{"description":"use {placeholder} text",'
            '"rationale":"contains } brace"}]}'
        )
        steps = LLMPlanBackend._parse_steps(text)
        assert len(steps) == 1
        assert "{placeholder}" in steps[0].description
        assert "} brace" in steps[0].rationale

    def test_returns_empty_on_no_braces(self):
        from core.cognitive.planner import LLMPlanBackend
        assert LLMPlanBackend._parse_steps("just plain text") == []

    def test_returns_empty_on_invalid_json(self):
        from core.cognitive.planner import LLMPlanBackend
        # Looks like a JSON object but isn't valid
        text = '{"steps": [not valid'
        assert LLMPlanBackend._parse_steps(text) == []

    def test_extract_first_json_object_helper(self):
        from core.cognitive.planner import LLMPlanBackend
        text = "before {a:1} middle {b:2} after"
        first = LLMPlanBackend._extract_first_json_object(text)
        assert first == "{a:1}"

    def test_extract_handles_escaped_quotes(self):
        from core.cognitive.planner import LLMPlanBackend
        text = '{"description":"line with \\"quotes\\" inside"}'
        first = LLMPlanBackend._extract_first_json_object(text)
        assert first == text


# ── replan() empty sub-plan keeps original step ─────────────


class TestReplanEmptySubPlan:
    def test_empty_subplan_keeps_failed_step(self):
        """Regression: previously when re-plan returned no steps,
        the merged plan had the failed step removed entirely."""
        from core.cognitive.planner import (
            HeuristicPlanBackend, LLMPlanBackend, Plan, PlanStep, Planner,
        )

        # Build a plan with three steps
        plan = Plan(goal_id="g1", goal_what="big goal", backend="heuristic")
        plan.steps = [
            PlanStep(description="step 1"),
            PlanStep(description="step 2 (will fail)"),
            PlanStep(description="step 3"),
        ]

        # Inject a backend that always returns empty
        class _EmptyBackend(HeuristicPlanBackend):
            name = "empty"
            def decompose(self, goal_what, *, context=None):
                return Plan(goal_id="", goal_what=goal_what, backend="empty")

        planner = Planner(backends=[_EmptyBackend()])
        merged = planner.replan(plan, failed_step_index=1)

        # Step 2 must still be present (kept rather than dropped)
        descriptions = [s.description for s in merged.steps]
        assert "step 1" in descriptions
        assert "step 2 (will fail)" in descriptions
        assert "step 3" in descriptions
        assert len(merged.steps) == 3
        assert merged.backend.endswith("replan-empty")

    def test_successful_subplan_replaces_failed_step(self):
        """Happy path still works: a non-empty re-plan replaces
        the failed step with the new sub-steps."""
        from core.cognitive.planner import (
            HeuristicPlanBackend, Plan, PlanStep, Planner,
        )

        plan = Plan(goal_id="g1", goal_what="big goal", backend="heuristic")
        plan.steps = [
            PlanStep(description="A"),
            PlanStep(description="B"),
            PlanStep(description="C"),
        ]

        # Backend that returns a 2-step sub-plan
        class _TwoStepBackend(HeuristicPlanBackend):
            name = "twostep"
            def decompose(self, goal_what, *, context=None):
                p = Plan(goal_id="", goal_what=goal_what, backend="twostep")
                p.steps = [PlanStep(description="B.1"), PlanStep(description="B.2")]
                return p

        planner = Planner(backends=[_TwoStepBackend()])
        merged = planner.replan(plan, failed_step_index=1)
        descriptions = [s.description for s in merged.steps]
        assert descriptions == ["A", "B.1", "B.2", "C"]

    def test_replan_invalid_index_returns_original_plan(self):
        from core.cognitive.planner import Plan, PlanStep, Planner
        plan = Plan(goal_id="g", goal_what="x", backend="h")
        plan.steps = [PlanStep(description="only")]
        planner = Planner(backends=[])
        # Out of range
        result = planner.replan(plan, failed_step_index=99)
        assert result is plan
        # Negative index
        result = planner.replan(plan, failed_step_index=-1)
        assert result is plan

    def test_replan_empty_plan_returns_original(self):
        from core.cognitive.planner import Plan, Planner
        plan = Plan(goal_id="g", goal_what="x", backend="h")
        planner = Planner(backends=[])
        result = planner.replan(plan, failed_step_index=0)
        assert result is plan


# ── End-to-end LLM backend with messy LLM output ────────────


class TestLLMPlanBackendIntegration:
    def test_messy_llm_output_still_parses(self):
        from core.cognitive.planner import LLMPlanBackend, Plan

        class _FakeResponse:
            success = True
            text = (
                "Sure, here is the plan:\n"
                "```json\n"
                '{"steps":[{"description":"do A","confidence":0.8},'
                '{"description":"do B","confidence":0.7}]}\n'
                "```\n"
                "Hope this helps! {extra: braces in chatter}"
            )

        class _FakeLLM:
            def ask(self, **k):
                return _FakeResponse()

        backend = LLMPlanBackend(llm=_FakeLLM())
        plan = backend.decompose("any goal")
        assert plan.step_count() == 2
        assert plan.steps[0].description == "do A"
        assert plan.steps[1].description == "do B"
