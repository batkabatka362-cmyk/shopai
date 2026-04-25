"""Plan repair tests."""
from __future__ import annotations

import unittest

from core.brain import plan_repair as pr


class TestRecipe(unittest.TestCase):
    def test_blank_step_raises(self) -> None:
        with self.assertRaises(ValueError):
            pr.FailureRecipe(
                step="", cause_match=lambda e: True,
                strategy="abort",
            )

    def test_bad_strategy_raises(self) -> None:
        with self.assertRaises(ValueError):
            pr.FailureRecipe(
                step="x", cause_match=lambda e: True,
                strategy="invalid",  # type: ignore
            )

    def test_substitute_without_substitute_step_raises(self) -> None:
        with self.assertRaises(ValueError):
            pr.FailureRecipe(
                step="x", cause_match=lambda e: True,
                strategy="substitute",
            )

    def test_retry_without_schedule_raises(self) -> None:
        with self.assertRaises(ValueError):
            pr.FailureRecipe(
                step="x", cause_match=lambda e: True,
                strategy="retry",
            )

    def test_matches_catches_raising_match(self) -> None:
        def bad(_):
            raise RuntimeError("x")

        r = pr.FailureRecipe(
            step="x", cause_match=bad, strategy="abort",
        )
        self.assertFalse(r.matches(RuntimeError("y")))


class TestRetry(unittest.TestCase):
    def setUp(self) -> None:
        self.p = pr.PlanRepairer()
        self.p.register(pr.FailureRecipe(
            step="fetch",
            cause_match=lambda e: "rate" in str(e).lower(),
            strategy="retry",
            retry_schedule_s=(5, 30, 120),
        ))

    def test_first_retry_uses_first_delay(self) -> None:
        act = self.p.decide("fetch", RuntimeError("Rate limit"), [])
        self.assertEqual(act.strategy, "retry")
        self.assertEqual(act.delay_s, 5)

    def test_retry_counter_advances(self) -> None:
        self.p.decide("fetch", RuntimeError("rate"), [])
        self.p.decide("fetch", RuntimeError("rate"), [])
        act = self.p.decide("fetch", RuntimeError("rate"), [])
        self.assertEqual(act.delay_s, 120)

    def test_retry_budget_exhausts_to_abort(self) -> None:
        for _ in range(3):
            self.p.decide("fetch", RuntimeError("rate"), [])
        act = self.p.decide("fetch", RuntimeError("rate"), [])
        self.assertEqual(act.strategy, "abort")
        self.assertTrue(act.escalate)

    def test_unrelated_exception_does_not_match(self) -> None:
        act = self.p.decide("fetch", RuntimeError("validation"), [])
        # No matching recipe → default abort
        self.assertEqual(act.strategy, "abort")


class TestSubstitute(unittest.TestCase):
    def test_substitute_swaps_step(self) -> None:
        p = pr.PlanRepairer()
        p.register(pr.FailureRecipe(
            step="publish",
            cause_match=lambda e: "validation" in str(e).lower(),
            strategy="substitute",
            substitute="publish_via_graphql",
        ))
        act = p.decide(
            "publish", RuntimeError("Validation failed"), [],
        )
        self.assertEqual(act.strategy, "substitute")
        self.assertEqual(act.next_step, "publish_via_graphql")


class TestSkip(unittest.TestCase):
    def test_skip_with_compensation(self) -> None:
        p = pr.PlanRepairer()
        p.register(pr.FailureRecipe(
            step="notify",
            cause_match=lambda e: True,
            strategy="skip",
            compensation="log_to_audit",
        ))
        act = p.decide(
            "notify", RuntimeError("slack down"),
            remaining_steps=["record_outcome"],
        )
        self.assertEqual(act.strategy, "skip")
        self.assertEqual(act.compensation, "log_to_audit")
        self.assertEqual(act.next_step, "record_outcome")


class TestAbort(unittest.TestCase):
    def test_explicit_abort(self) -> None:
        p = pr.PlanRepairer()
        p.register(pr.FailureRecipe(
            step="charge",
            cause_match=lambda e: "fraud" in str(e).lower(),
            strategy="abort",
            description="stop on fraud trip",
        ))
        act = p.decide("charge", RuntimeError("fraud flag"), [])
        self.assertEqual(act.strategy, "abort")
        self.assertTrue(act.escalate)
        self.assertIn("fraud", act.reason)

    def test_default_abort_when_no_recipe(self) -> None:
        p = pr.PlanRepairer()
        act = p.decide("whatever", RuntimeError("boom"), [])
        self.assertEqual(act.strategy, "abort")
        self.assertTrue(act.escalate)


class TestRegistry(unittest.TestCase):
    def test_unregister_step(self) -> None:
        p = pr.PlanRepairer()
        p.register(pr.FailureRecipe(
            step="x", cause_match=lambda e: True,
            strategy="retry", retry_schedule_s=(1,),
        ))
        n = p.unregister_step("x")
        self.assertEqual(n, 1)
        self.assertEqual(p.recipes_for("x"), [])

    def test_multiple_recipes_first_match_wins(self) -> None:
        p = pr.PlanRepairer()
        p.register(pr.FailureRecipe(
            step="x", strategy="substitute", substitute="y",
            cause_match=lambda e: "foo" in str(e),
        ))
        p.register(pr.FailureRecipe(
            step="x", strategy="abort",
            cause_match=lambda e: True,
        ))
        # Foo matches first recipe → substitute
        self.assertEqual(
            p.decide("x", RuntimeError("foo error"), []).strategy,
            "substitute",
        )
        # Non-foo matches the second → abort
        self.assertEqual(
            p.decide("x", RuntimeError("bar"), []).strategy,
            "abort",
        )

    def test_reset_clears_retry_state(self) -> None:
        p = pr.PlanRepairer()
        p.register(pr.FailureRecipe(
            step="x", cause_match=lambda e: True,
            strategy="retry", retry_schedule_s=(1, 2),
        ))
        p.decide("x", RuntimeError(), [])
        p.reset_state()
        act = p.decide("x", RuntimeError(), [])
        self.assertEqual(act.delay_s, 1)  # back to first delay


class TestStats(unittest.TestCase):
    def test_stats_reports_counts(self) -> None:
        p = pr.PlanRepairer()
        p.register(pr.FailureRecipe(
            step="x", cause_match=lambda e: True,
            strategy="retry", retry_schedule_s=(1,),
        ))
        s = p.stats()
        self.assertEqual(s["recipes"], 1)


class TestDict(unittest.TestCase):
    def test_action_as_dict(self) -> None:
        act = pr.RepairAction(
            strategy="retry", next_step="x",
            delay_s=5.0, reason="r",
        )
        d = act.as_dict()
        self.assertEqual(d["strategy"], "retry")
        self.assertEqual(d["delay_s"], 5.0)


if __name__ == "__main__":
    unittest.main()
