"""AGI cycle tests."""
from __future__ import annotations

import unittest

from core.brain import agi_cycle as ac


class TestBasic(unittest.TestCase):
    def test_minimal_observation_runs_all_stages(self) -> None:
        r = ac.run_cycle({
            "kind": "order",
            "niche": "audio",
            "value": 120.0,
            "score": 3.5,
        })
        stage_names = [s.name for s in r.stages]
        for expected in (
            "working_memory", "epistemic", "surprise",
            "world_model", "policy_match", "tree_search",
            "decision", "hypothesis", "monologue", "self_prompt",
        ):
            self.assertIn(expected, stage_names)

    def test_skip_list_honoured(self) -> None:
        r = ac.run_cycle(
            {"kind": "event"},
            skip=["tree_search", "hypothesis"],
        )
        skipped = [s.name for s in r.stages
                    if s.status == "skipped"]
        self.assertIn("tree_search", skipped)
        self.assertIn("hypothesis", skipped)

    def test_world_model_skips_when_action_missing(self) -> None:
        r = ac.run_cycle({"kind": "ping"})
        wm_stage = next(s for s in r.stages
                         if s.name == "world_model")
        # No action/kpi/value → stage returns skipped detail but
        # status is still "ok" because we handled it cleanly.
        self.assertEqual(wm_stage.status, "ok")
        self.assertIn("skipped", str(wm_stage.detail))


class TestWithGovernor(unittest.TestCase):
    def test_candidate_action_invokes_governor(self) -> None:
        from core.brain import dual_process as dp
        from core.brain import decision_governor as dg
        from core.brain import safety_envelope as sf
        arbiter = dp.DualProcessArbiter(
            system1_fn=lambda action: {**action, "handled_by": "fast"},
            system2_fn=lambda action: {**action, "handled_by": "slow"},
        )
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        r = ac.run_cycle(
            observation={"kind": "audio_launch", "niche": "audio",
                          "price_band": "mid"},
            candidate_action={"kind": "launch", "spend_usd": 20},
            stakes=0.1, confidence=0.9,
            governor=gov,
        )
        self.assertIsNotNone(r.chosen_action)
        self.assertEqual(r.decision_status, "allowed")

    def test_governor_blocks_unethical(self) -> None:
        from core.brain import dual_process as dp
        from core.brain import decision_governor as dg
        from core.brain import safety_envelope as sf
        arbiter = dp.DualProcessArbiter(
            system1_fn=lambda x: x, system2_fn=lambda x: x,
        )
        gov = dg.DecisionGovernor(
            arbiter=arbiter,
            envelope_builder=lambda ctx: sf.Envelope(),
        )
        r = ac.run_cycle(
            observation={"kind": "price_set", "niche": "audio"},
            candidate_action={
                "kind": "set_price",
                "price": 29.0,
                "compare_at_price": 999.0,
                "verified_historical_max_price": 50.0,
            },
            stakes=0.1, confidence=0.9,
            governor=gov,
        )
        self.assertEqual(r.decision_status, "blocked")
        self.assertIsNone(r.chosen_action)


class TestStageFailureIsolation(unittest.TestCase):
    def test_single_bad_stage_does_not_crash_cycle(self) -> None:
        # Feeding a malformed observation — world_model update asks
        # for float(value) and can raise; but cycle should still
        # complete with that stage marked error (or skipped).
        r = ac.run_cycle({
            "kind": "order",
            "action": "scale",
            "kpi": "roas",
            "value": "not_a_number",
        })
        # Cycle should have run all stages
        self.assertGreater(len(r.stages), 5)


class TestReportShape(unittest.TestCase):
    def test_elapsed_positive(self) -> None:
        r = ac.run_cycle({})
        self.assertGreater(r.elapsed_ms, 0)

    def test_as_dict_serialises(self) -> None:
        r = ac.run_cycle({"kind": "x"})
        d = r.as_dict()
        self.assertIn("stages", d)
        self.assertIn("elapsed_ms", d)


if __name__ == "__main__":
    unittest.main()
