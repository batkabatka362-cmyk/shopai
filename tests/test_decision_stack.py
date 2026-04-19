"""Decision stack tests."""
from __future__ import annotations

import unittest

from core.brain import decision_stack as ds


class TestEmptyStack(unittest.TestCase):
    def test_all_stages_skipped(self) -> None:
        stack = ds.DecisionStack()
        report = stack.decide(observation={"x": 1})
        statuses = [v.status for v in report.stage_verdicts]
        self.assertEqual(statuses, ["skipped"] * 6)
        # Candidate passes through unchanged (None here)
        self.assertIsNone(report.final_action)

    def test_candidate_passes_through(self) -> None:
        stack = ds.DecisionStack()
        report = stack.decide(
            observation={},
            candidate_action={"kind": "scale"},
        )
        # No stage blocked → candidate survives
        self.assertEqual(
            report.final_action, {"kind": "scale"},
        )


class TestFullChain(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[str] = []

        def mk(name, status="ok", payload=None):
            def fn(ctx):
                self.calls.append(name)
                out = {"status": status, "note": name}
                if payload is not None:
                    out["payload"] = payload
                return out
            return fn

        self.stack = ds.DecisionStack(stages=ds.StageCallables(
            attention=mk("attention"),
            evidence=mk("evidence"),
            deliberate=mk(
                "deliberate",
                payload={"candidate": {"kind": "scale"}},
            ),
            safety=mk("safety"),
            feasibility=mk("feasibility"),
            utility=mk("utility"),
        ))

    def test_all_stages_run_in_order(self) -> None:
        report = self.stack.decide(observation={"x": 1})
        self.assertEqual(
            self.calls,
            [
                "attention", "evidence", "deliberate",
                "safety", "feasibility", "utility",
            ],
        )
        self.assertEqual(
            report.final_action, {"kind": "scale"},
        )

    def test_deliberate_proposed_action_visible_to_later_stages(
        self,
    ) -> None:
        # safety stage records the candidate it saw
        seen: dict[str, Any] = {}

        def safety(ctx):
            seen["action"] = ctx.get("candidate_action")
            return {"status": "ok"}

        self.stack._stages.safety = safety   # type: ignore[attr-defined]
        self.stack.decide(
            observation={},
            candidate_action={"kind": "initial"},
        )
        # Deliberate replaced the candidate; safety should see the new one
        self.assertEqual(
            seen["action"], {"kind": "scale"},
        )


class TestBlocking(unittest.TestCase):
    def test_attention_blocks_short_circuits(self) -> None:
        calls: list[str] = []

        def mk(name, status="ok"):
            def fn(ctx):
                calls.append(name)
                return {"status": status, "note": f"{name}-note"}
            return fn

        stack = ds.DecisionStack(stages=ds.StageCallables(
            attention=mk("attention", status="blocked"),
            evidence=mk("evidence"),
            deliberate=mk("deliberate"),
            safety=mk("safety"),
            feasibility=mk("feasibility"),
            utility=mk("utility"),
        ))
        report = stack.decide(
            observation={},
            candidate_action={"kind": "x"},
        )
        self.assertEqual(calls, ["attention"])
        self.assertIsNone(report.final_action)
        self.assertIn("attention", report.block_reason)

    def test_safety_block_after_earlier_ok(self) -> None:
        calls: list[str] = []

        def ok(name):
            def fn(ctx):
                calls.append(name)
                return {"status": "ok"}
            return fn

        def blocker(ctx):
            calls.append("safety")
            return {"status": "blocked", "note": "bright_line"}

        stack = ds.DecisionStack(stages=ds.StageCallables(
            attention=ok("attention"),
            evidence=ok("evidence"),
            deliberate=ok("deliberate"),
            safety=blocker,
            feasibility=ok("feasibility"),
            utility=ok("utility"),
        ))
        report = stack.decide(
            observation={}, candidate_action={"kind": "x"},
        )
        self.assertEqual(
            calls,
            ["attention", "evidence", "deliberate", "safety"],
        )
        self.assertIn("safety", report.block_reason)
        self.assertIn("bright_line", report.block_reason)


class TestErrorHandling(unittest.TestCase):
    def test_raising_stage_treated_error(self) -> None:
        def boom(ctx):
            raise RuntimeError("explode")

        stack = ds.DecisionStack(stages=ds.StageCallables(
            attention=boom,
        ))
        report = stack.decide(observation={})
        self.assertEqual(
            report.stage_verdicts[0].status, "error",
        )
        self.assertIn(
            "error", report.block_reason,
        )

    def test_non_dict_return_error(self) -> None:
        def weird(ctx):
            return "not a dict"

        stack = ds.DecisionStack(stages=ds.StageCallables(
            evidence=weird,
        ))
        report = stack.decide(observation={})
        # evidence stage at index 1 → attention was skipped first
        ev = [
            v for v in report.stage_verdicts
            if v.stage == "evidence"
        ][0]
        self.assertEqual(ev.status, "error")

    def test_unknown_status_becomes_error(self) -> None:
        def weird(ctx):
            return {"status": "maybe_maybe"}

        stack = ds.DecisionStack(stages=ds.StageCallables(
            deliberate=weird,
        ))
        report = stack.decide(observation={})
        delib = [
            v for v in report.stage_verdicts
            if v.stage == "deliberate"
        ][0]
        self.assertEqual(delib.status, "error")


class TestStakesClamp(unittest.TestCase):
    def test_stakes_clamped_to_unit(self) -> None:
        stack = ds.DecisionStack()
        high = stack.decide(observation={}, stakes=5.0)
        low = stack.decide(observation={}, stakes=-1.0)
        self.assertEqual(high.stakes, 1.0)
        self.assertEqual(low.stakes, 0.0)


class TestStats(unittest.TestCase):
    def test_stats_and_registered(self) -> None:
        stack = ds.DecisionStack(stages=ds.StageCallables(
            attention=lambda ctx: {"status": "ok"},
            safety=lambda ctx: {"status": "ok"},
        ))
        self.assertEqual(
            stack.registered_stages(),
            ["attention", "safety"],
        )
        self.assertEqual(stack.stats()["stages_registered"], 2)


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        stack = ds.DecisionStack(stages=ds.StageCallables(
            attention=lambda ctx: {"status": "ok"},
        ))
        d = stack.decide(
            observation={"x": 1}, candidate_action={"kind": "y"},
        ).as_dict()
        self.assertIn("stage_verdicts", d)
        self.assertIn("final_action", d)


if __name__ == "__main__":
    unittest.main()
