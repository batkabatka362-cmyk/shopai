"""Plan verifier tests."""
from __future__ import annotations

import unittest

from core.brain import plan_verifier as pv


def _set_key(key, value):
    def effect(state):
        out = dict(state)
        out[key] = value
        return out
    return effect


def _require_key(key):
    def pre(state):
        return key in state
    return pre


class TestPlanStep(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            pv.PlanStep(name="", precondition=lambda s: True,
                        effect=lambda s: s)


class TestInvariant(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            pv.NamedInvariant(name="", predicate=lambda s: True)

    def test_bad_severity_raises(self) -> None:
        with self.assertRaises(ValueError):
            pv.NamedInvariant(
                name="x", predicate=lambda s: True,
                severity="high",  # type: ignore
            )

    def test_raising_predicate_fails_closed(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        inv = pv.NamedInvariant(name="x", predicate=boom)
        self.assertFalse(inv.holds({}))


class TestAllGreen(unittest.TestCase):
    def test_simple_plan_passes(self) -> None:
        steps = [
            pv.PlanStep(
                "ingest",
                precondition=lambda s: True,
                effect=_set_key("ingested", True),
            ),
            pv.PlanStep(
                "publish",
                precondition=_require_key("ingested"),
                effect=_set_key("published", True),
            ),
        ]
        v = pv.PlanVerifier()
        report = v.verify({}, steps)
        self.assertEqual(report.verdict, "ok")
        self.assertEqual(len(report.steps), 2)
        self.assertTrue(report.final_state["published"])


class TestPreconditionFailure(unittest.TestCase):
    def test_blocked_on_missing_key(self) -> None:
        steps = [
            pv.PlanStep(
                "publish",
                precondition=_require_key("ingested"),
                effect=_set_key("published", True),
            ),
        ]
        v = pv.PlanVerifier()
        report = v.verify({}, steps)
        self.assertEqual(report.verdict, "blocked")
        self.assertIn("precondition:publish", report.violations)


class TestInvariantBreach(unittest.TestCase):
    def test_hard_invariant_blocks(self) -> None:
        steps = [
            pv.PlanStep(
                "drop",
                precondition=lambda s: True,
                effect=_set_key("inventory", -5),
            ),
        ]
        v = pv.PlanVerifier()
        v.add_invariant(pv.NamedInvariant(
            name="inventory_non_negative",
            predicate=lambda s: s.get("inventory", 0) >= 0,
            severity="hard",
        ))
        report = v.verify({}, steps)
        self.assertEqual(report.verdict, "blocked")
        self.assertTrue(any(
            "invariant:inventory_non_negative:hard" in v
            for v in report.violations
        ))

    def test_soft_invariant_warns(self) -> None:
        steps = [
            pv.PlanStep(
                "raise_price",
                precondition=lambda s: True,
                effect=_set_key("price", 9999.0),
            ),
        ]
        v = pv.PlanVerifier()
        v.add_invariant(pv.NamedInvariant(
            name="reasonable_price",
            predicate=lambda s: float(s.get("price", 0)) < 100.0,
            severity="soft",
        ))
        report = v.verify({}, steps)
        self.assertEqual(report.verdict, "warnings")


class TestNoop(unittest.TestCase):
    def test_noop_step_flagged_in_notes(self) -> None:
        steps = [
            pv.PlanStep(
                "nothing",
                precondition=lambda s: True,
                effect=lambda s: s,   # identity
            ),
        ]
        v = pv.PlanVerifier()
        report = v.verify({"x": 1}, steps)
        self.assertIn("no_op", report.steps[0].notes)


class TestEffectException(unittest.TestCase):
    def test_effect_raise_blocks_plan(self) -> None:
        def boom(_s):
            raise RuntimeError("x")

        steps = [
            pv.PlanStep(
                "bad", precondition=lambda s: True, effect=boom,
            ),
        ]
        v = pv.PlanVerifier()
        report = v.verify({}, steps)
        self.assertEqual(report.verdict, "blocked")
        self.assertIn("effect_error:bad", report.violations)


class TestPreconditionsOnly(unittest.TestCase):
    def test_returns_failing_steps(self) -> None:
        steps = [
            pv.PlanStep(
                "a",
                precondition=_require_key("x"),
                effect=_set_key("y", 1),
            ),
            pv.PlanStep(
                "b",
                precondition=lambda s: True,
                effect=_set_key("z", 1),
            ),
        ]
        v = pv.PlanVerifier()
        failed = v.preconditions_only({}, steps)
        self.assertEqual(failed, ["a"])

    def test_raising_predicate_counts_as_failure(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        steps = [pv.PlanStep("a", precondition=boom, effect=lambda s: s)]
        v = pv.PlanVerifier()
        self.assertEqual(
            v.preconditions_only({}, steps), ["a"],
        )


class TestHardBreakStopsPropagation(unittest.TestCase):
    def test_subsequent_steps_not_visible_after_hard_break(self) -> None:
        steps = [
            pv.PlanStep(
                "bad",
                precondition=lambda s: True,
                effect=_set_key("inventory", -1),
            ),
            pv.PlanStep(
                "later",
                precondition=lambda s: True,
                effect=_set_key("later", True),
            ),
        ]
        v = pv.PlanVerifier()
        v.add_invariant(pv.NamedInvariant(
            name="inv_nn",
            predicate=lambda s: s.get("inventory", 0) >= 0,
            severity="hard",
        ))
        report = v.verify({"inventory": 5}, steps)
        self.assertEqual(report.verdict, "blocked")
        # Only "bad" ran
        step_names = [s.step for s in report.steps]
        self.assertEqual(step_names, ["bad"])


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        v = pv.PlanVerifier()
        v.add_invariant(pv.NamedInvariant("a", lambda s: True))
        v.add_invariant(
            pv.NamedInvariant("b", lambda s: True, severity="soft"),
        )
        s = v.stats()
        self.assertEqual(s["invariants"], 2)
        self.assertEqual(s["hard_invariants"], 1)


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        steps = [
            pv.PlanStep(
                "a", precondition=lambda s: True,
                effect=_set_key("x", 1),
            ),
        ]
        v = pv.PlanVerifier()
        d = v.verify({}, steps).as_dict()
        self.assertIn("steps", d)
        self.assertIn("verdict", d)


if __name__ == "__main__":
    unittest.main()
