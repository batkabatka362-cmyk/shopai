"""Skill gym tests."""
from __future__ import annotations

import unittest

from core.brain import skill_gym as sg
from core.brain import world_simulator as ws


def _build_sim() -> ws.WorldSimulator:
    sim = ws.WorldSimulator()
    for kind, fn in ws.default_transitions().items():
        sim.register(kind, fn)
    return sim


class TestScenario(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            sg.GymScenario(
                name="",
                initial_state={},
                actions=[],
                validate=lambda s: True,
            )


class TestEvaluate(unittest.TestCase):
    def setUp(self) -> None:
        self.gym = sg.SkillGym(simulator=_build_sim())

    def test_blank_skill_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.gym.evaluate("", [])

    def test_all_strict_passing_is_ready(self) -> None:
        scenarios = [
            sg.GymScenario(
                name="price_update",
                initial_state={"products": {"p1": {"price": 10.0}}},
                actions=[{
                    "kind": "set_price",
                    "sku": "p1", "price": 25.0,
                }],
                validate=lambda s: (
                    s["products"]["p1"]["price"] == 25.0
                ),
            ),
        ]
        report = self.gym.evaluate("raise_price", scenarios)
        self.assertEqual(report.recommendation, "ready")
        self.assertEqual(report.pass_rate, 1.0)

    def test_strict_failure_rejects(self) -> None:
        scenarios = [
            sg.GymScenario(
                name="bad_strict",
                initial_state={"products": {}},
                actions=[{
                    "kind": "set_price",
                    "sku": "", "price": 10,
                }],   # empty sku → noop
                validate=lambda s: (
                    "p1" in s.get("products", {})
                ),
                strict=True,
            ),
        ]
        report = self.gym.evaluate("x", scenarios)
        self.assertEqual(report.recommendation, "reject")

    def test_soft_failure_is_conditional(self) -> None:
        scenarios = [
            sg.GymScenario(
                name="strict_ok",
                initial_state={"products": {"p1": {}}},
                actions=[{
                    "kind": "set_price",
                    "sku": "p1", "price": 10,
                }],
                validate=lambda s: (
                    s["products"]["p1"]["price"] == 10.0
                ),
                strict=True,
            ),
            sg.GymScenario(
                name="soft_edge_case_fails",
                initial_state={"products": {}},
                actions=[],
                validate=lambda s: False,   # always fails
                strict=False,
            ),
        ]
        report = self.gym.evaluate("x", scenarios)
        self.assertEqual(report.recommendation, "conditional")

    def test_all_strict_pass_no_soft_is_ready(self) -> None:
        scenarios = [
            sg.GymScenario(
                name="s1",
                initial_state={},
                actions=[],
                validate=lambda s: True,
                strict=True,
            ),
            sg.GymScenario(
                name="s2",
                initial_state={},
                actions=[],
                validate=lambda s: True,
                strict=True,
            ),
        ]
        report = self.gym.evaluate("x", scenarios)
        self.assertEqual(report.recommendation, "ready")

    def test_empty_scenarios_rejects(self) -> None:
        report = self.gym.evaluate("x", [])
        self.assertEqual(report.recommendation, "reject")
        self.assertEqual(report.pass_rate, 0.0)


class TestExceptionHandling(unittest.TestCase):
    def setUp(self) -> None:
        self.gym = sg.SkillGym(simulator=_build_sim())

    def test_validate_raise_counts_as_fail(self) -> None:
        def boom(state):
            raise RuntimeError("bug in validator")

        scenarios = [
            sg.GymScenario(
                name="s",
                initial_state={},
                actions=[],
                validate=boom,
                strict=True,
            ),
        ]
        report = self.gym.evaluate("x", scenarios)
        self.assertEqual(report.recommendation, "reject")
        self.assertIn(
            "validate_raised",
            report.scenarios[0].note,
        )


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        gym = sg.SkillGym(simulator=_build_sim())
        report = gym.evaluate("x", [
            sg.GymScenario(
                name="ok",
                initial_state={},
                actions=[],
                validate=lambda s: True,
            ),
        ])
        d = report.as_dict()
        self.assertIn("scenarios", d)
        self.assertIn("recommendation", d)


class TestStats(unittest.TestCase):
    def test_stats(self) -> None:
        gym = sg.SkillGym(simulator=_build_sim())
        s = gym.stats()
        self.assertTrue(s["simulator_ready"])


if __name__ == "__main__":
    unittest.main()
