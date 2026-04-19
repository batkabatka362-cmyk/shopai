"""Counterfactual simulator tests."""
from __future__ import annotations

import random
import unittest

from core.brain import counterfactual_simulator as cs


def _linear_transition(rewards: dict[str, float]):
    def fn(state, action):
        new = dict(state)
        new["step"] = state.get("step", 0) + 1
        return new, rewards.get(action, 0.0)
    return fn


class TestSimulate(unittest.TestCase):
    def test_fixed_sequence(self) -> None:
        tr = _linear_transition({"a": 1.0, "b": 2.0, "c": 0.5})
        r = cs.simulate({}, ["a", "b", "c"], tr)
        self.assertAlmostEqual(r.total_reward, 3.5)
        self.assertEqual(len(r.steps), 3)

    def test_max_steps_caps(self) -> None:
        tr = _linear_transition({"a": 1.0})
        r = cs.simulate({}, ["a"] * 10, tr, max_steps=3)
        self.assertEqual(len(r.steps), 3)

    def test_transition_raise_truncates(self) -> None:
        def tr(state, action):
            if action == "bad":
                raise RuntimeError("x")
            return state, 1.0

        r = cs.simulate({}, ["a", "bad", "c"], tr)
        self.assertEqual(len(r.steps), 1)


class TestCompareAlternatives(unittest.TestCase):
    def test_better_action_ranked_first(self) -> None:
        tr = _linear_transition({"scale": 5.0, "kill": -1.0, "wait": 0.0})

        def policy(state, rng):
            # After first step, keep doing "wait"
            return "wait"

        reports = cs.compare_alternatives(
            {}, ["scale", "kill"],
            tr, policy, horizon=3, trials=5, seed=42,
        )
        self.assertEqual(reports[0].first_action, "scale")

    def test_horizon_controls_rollout(self) -> None:
        tr = _linear_transition({"a": 1.0, "b": 1.0})

        def policy(state, rng):
            return "b"

        reports = cs.compare_alternatives(
            {}, ["a"], tr, policy,
            horizon=10, trials=1, seed=0,
        )
        # a pays 1, then 9 more steps of b pay 1 each = 10
        self.assertAlmostEqual(reports[0].mean_return, 10.0)

    def test_empty_alternatives(self) -> None:
        self.assertEqual(
            cs.compare_alternatives(
                {}, [], lambda s, a: (s, 0), lambda s, r: None,
            ),
            [],
        )

    def test_invalid_horizon_raises(self) -> None:
        with self.assertRaises(ValueError):
            cs.compare_alternatives(
                {}, ["a"],
                lambda s, a: (s, 0),
                lambda s, r: None,
                horizon=0,
            )

    def test_invalid_trials_raises(self) -> None:
        with self.assertRaises(ValueError):
            cs.compare_alternatives(
                {}, ["a"],
                lambda s, a: (s, 0),
                lambda s, r: None,
                trials=0,
            )

    def test_stochastic_policy_produces_variance(self) -> None:
        def tr(state, action):
            return state, {"win": 5.0, "lose": -3.0}.get(action, 0.0)

        def policy(state, rng):
            return rng.choice(["win", "lose"])

        reports = cs.compare_alternatives(
            {}, ["win"], tr, policy,
            horizon=5, trials=30, seed=42,
        )
        self.assertGreater(reports[0].stdev_return, 0.0)
        self.assertLess(reports[0].worst_case, reports[0].best_case)

    def test_policy_none_ends_rollout(self) -> None:
        tr = _linear_transition({"a": 1.0})

        def policy(state, rng):
            return None   # stop immediately after first forced action

        reports = cs.compare_alternatives(
            {}, ["a"], tr, policy, horizon=10, trials=1, seed=0,
        )
        # Only 1 step of reward, not 10
        self.assertAlmostEqual(reports[0].mean_return, 1.0)


class TestRiskAdjusted(unittest.TestCase):
    def test_picks_high_mean_low_variance(self) -> None:
        reports = [
            cs.AlternativeReport(
                first_action="risky", mean_return=10.0,
                stdev_return=20.0,
                worst_case=-10, best_case=30,
                n_trials=10, horizon=1,
            ),
            cs.AlternativeReport(
                first_action="stable", mean_return=8.0,
                stdev_return=1.0,
                worst_case=6, best_case=10,
                n_trials=10, horizon=1,
            ),
        ]
        best = cs.risk_adjusted_best(reports, risk_aversion=1.0)
        # 10 - 20 = -10 vs 8 - 1 = 7 → stable wins
        self.assertEqual(best.first_action, "stable")

    def test_zero_risk_aversion_picks_highest_mean(self) -> None:
        reports = [
            cs.AlternativeReport(
                "a", 10.0, 20.0, -10, 30, 10, 1,
            ),
            cs.AlternativeReport(
                "b", 8.0, 1.0, 6, 10, 10, 1,
            ),
        ]
        best = cs.risk_adjusted_best(reports, risk_aversion=0.0)
        self.assertEqual(best.first_action, "a")

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(cs.risk_adjusted_best([]))


class TestDict(unittest.TestCase):
    def test_rollout_as_dict(self) -> None:
        tr = _linear_transition({"a": 1.0})
        r = cs.simulate({}, ["a"], tr)
        d = r.as_dict()
        self.assertEqual(d["n_steps"], 1)
        self.assertEqual(d["actions"], ["a"])

    def test_alternative_report_as_dict(self) -> None:
        ar = cs.AlternativeReport(
            "a", 5.0, 1.0, 3, 7, 10, 3,
        )
        d = ar.as_dict()
        self.assertEqual(d["first_action"], "a")


if __name__ == "__main__":
    unittest.main()
