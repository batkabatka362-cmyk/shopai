"""Verify v24 brain hooks never break the autonomous cycle.

The hooks are opt-in via SHOPAI_BRAIN_HOOKS=1 and wrapped in try/except
inside run_cycle. These tests exercise the *import path* and the
*off-by-default* behaviour — the full cycle itself needs Shopify +
other heavyweight fixtures we don't replicate here.
"""
from __future__ import annotations

import os
import unittest


class TestHooksOffByDefault(unittest.TestCase):
    def test_default_env_not_set(self) -> None:
        # Clean environment check: SHOPAI_BRAIN_HOOKS isn't set
        # automatically. The cycle must still function.
        os.environ.pop("SHOPAI_BRAIN_HOOKS", None)
        # Import should work regardless.
        from core.autonomous.controller import AutonomousController
        self.assertTrue(AutonomousController)

    def test_hooks_on_imports_cleanly(self) -> None:
        os.environ["SHOPAI_BRAIN_HOOKS"] = "1"
        import importlib
        from core.autonomous import controller
        importlib.reload(controller)
        self.assertTrue(controller.AutonomousController)
        del os.environ["SHOPAI_BRAIN_HOOKS"]


class TestBrainFacadeHookSurfaces(unittest.TestCase):
    """The facade should have the methods we're calling from the hook."""

    def test_rank_by_attention_on_brain(self) -> None:
        from core.brain.brain_facade import brain
        self.assertTrue(hasattr(brain(), "rank_by_attention"))

    def test_housekeep_on_brain(self) -> None:
        from core.brain.brain_facade import brain
        self.assertTrue(hasattr(brain(), "housekeep"))

    def test_think_on_brain(self) -> None:
        from core.brain.brain_facade import brain
        self.assertTrue(hasattr(brain(), "think"))


class TestExperienceRecorderSurfaces(unittest.TestCase):
    def test_record_phase_present(self) -> None:
        from core.brain.experience_recorder import record_phase
        self.assertTrue(callable(record_phase))

    def test_record_outcome_present(self) -> None:
        from core.brain.experience_recorder import record_outcome
        self.assertTrue(callable(record_outcome))

    def test_record_assessment_present(self) -> None:
        from core.brain.experience_recorder import record_assessment
        self.assertTrue(callable(record_assessment))


class TestLLMGatewaySurfaces(unittest.TestCase):
    def test_ask_present(self) -> None:
        from core.llm_gateway import ask, GatewayResult
        self.assertTrue(callable(ask))
        self.assertTrue(GatewayResult)

    def test_stats_present(self) -> None:
        from core.llm_gateway import stats
        s = stats()
        self.assertIn("total_calls", s)


class TestCyclePlannerSurfaces(unittest.TestCase):
    def test_plan_next_cycle_present(self) -> None:
        from core.brain.cycle_planner import plan_next_cycle
        self.assertTrue(callable(plan_next_cycle))


if __name__ == "__main__":
    unittest.main()
