"""Scenario planner tests."""
from __future__ import annotations

import unittest

from core.brain import scenario_planner as sp


class TestSpec(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            sp.ScenarioSpec(
                name="",
                starting_state={},
                branches=[sp.Branch(label="a", weight=1.0)],
            )

    def test_empty_branches_raises(self) -> None:
        with self.assertRaises(ValueError):
            sp.ScenarioSpec(
                name="n", starting_state={}, branches=[],
            )

    def test_zero_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            sp.ScenarioSpec(
                name="n",
                starting_state={},
                branches=[sp.Branch(label="a", weight=0)],
            )


class TestPlan(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = sp.ScenarioPlanner()

    def test_plan_distributes_probability(self) -> None:
        spec = sp.ScenarioSpec(
            name="t",
            starting_state={"x": 1},
            branches=[
                sp.Branch(label="up", weight=3.0),
                sp.Branch(label="down", weight=1.0),
            ],
        )
        bundle = self.planner.plan(spec)
        probs = [s.probability for s in bundle.scenarios]
        self.assertAlmostEqual(sum(probs), 1.0, places=4)
        self.assertAlmostEqual(probs[0], 0.75, places=4)

    def test_branch_modifier_applied(self) -> None:
        spec = sp.ScenarioSpec(
            name="t",
            starting_state={"price": 20.0},
            branches=[
                sp.Branch(
                    label="hike",
                    weight=1.0,
                    modifier={"price": 25.0},
                ),
                sp.Branch(
                    label="cut",
                    weight=1.0,
                    modifier={"price": 15.0},
                ),
            ],
        )
        bundle = self.planner.plan(spec)
        prices = sorted(
            s.state_projection["price"]
            for s in bundle.scenarios
        )
        self.assertEqual(prices, [15.0, 25.0])

    def test_transform_applied(self) -> None:
        def double(s):
            out = dict(s)
            out["x"] = out["x"] * 2
            return out

        spec = sp.ScenarioSpec(
            name="t",
            starting_state={"x": 5},
            branches=[
                sp.Branch(
                    label="double", weight=1.0,
                    transform=double,
                ),
            ],
        )
        bundle = self.planner.plan(spec)
        self.assertEqual(
            bundle.scenarios[0].state_projection["x"], 10,
        )


class TestValueFn(unittest.TestCase):
    def setUp(self) -> None:
        self.planner = sp.ScenarioPlanner()

    def test_expected_value_weighted(self) -> None:
        spec = sp.ScenarioSpec(
            name="t",
            starting_state={"roas": 1.0},
            branches=[
                sp.Branch(
                    label="high", weight=1.0,
                    modifier={"roas": 2.0},
                ),
                sp.Branch(
                    label="low", weight=1.0,
                    modifier={"roas": 1.0},
                ),
            ],
        )
        bundle = self.planner.plan(
            spec,
            value_fn=lambda s: float(s["roas"]),
        )
        ev = self.planner.expected_value(bundle)
        self.assertAlmostEqual(ev, 1.5, places=4)

    def test_regret_bounds(self) -> None:
        spec = sp.ScenarioSpec(
            name="t",
            starting_state={"v": 1.0},
            branches=[
                sp.Branch(
                    label="high", weight=1.0,
                    modifier={"v": 3.0},
                ),
                sp.Branch(
                    label="low", weight=1.0,
                    modifier={"v": 1.0},
                ),
            ],
        )
        bundle = self.planner.plan(
            spec, value_fn=lambda s: float(s["v"]),
        )
        downside, upside = self.planner.regret_bounds(bundle)
        # mean = 2; min=1, max=3
        self.assertAlmostEqual(downside, 1.0)
        self.assertAlmostEqual(upside, 1.0)

    def test_failing_value_fn_yields_none(self) -> None:
        def boom(s):
            raise RuntimeError("nope")

        spec = sp.ScenarioSpec(
            name="t",
            starting_state={"v": 1.0},
            branches=[
                sp.Branch(label="a", weight=1.0),
            ],
        )
        bundle = self.planner.plan(spec, value_fn=boom)
        self.assertIsNone(bundle.scenarios[0].expected_value)

    def test_no_value_fn_pwv_is_none(self) -> None:
        spec = sp.ScenarioSpec(
            name="t",
            starting_state={},
            branches=[sp.Branch(label="a", weight=1.0)],
        )
        bundle = self.planner.plan(spec)
        self.assertIsNone(bundle.probability_weighted_value)


class TestQueries(unittest.TestCase):
    def test_recent(self) -> None:
        p = sp.ScenarioPlanner()
        for i in range(3):
            spec = sp.ScenarioSpec(
                name=f"s{i}",
                starting_state={},
                branches=[
                    sp.Branch(label="a", weight=1.0),
                ],
            )
            p.plan(spec)
        r = p.recent(limit=2)
        self.assertEqual(len(r), 2)

    def test_stats(self) -> None:
        p = sp.ScenarioPlanner()
        spec = sp.ScenarioSpec(
            name="s",
            starting_state={},
            branches=[sp.Branch(label="a", weight=1.0)],
        )
        p.plan(spec)
        s = p.stats()
        self.assertEqual(s["bundles"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        p = sp.ScenarioPlanner()
        spec = sp.ScenarioSpec(
            name="s",
            starting_state={},
            branches=[sp.Branch(label="a", weight=1.0)],
        )
        p.plan(spec)
        self.assertEqual(p.reset(), 1)


class TestDict(unittest.TestCase):
    def test_scenario_serialises(self) -> None:
        p = sp.ScenarioPlanner()
        spec = sp.ScenarioSpec(
            name="s",
            starting_state={"x": 1},
            branches=[sp.Branch(label="a", weight=1.0)],
        )
        bundle = p.plan(spec)
        d = bundle.scenarios[0].as_dict()
        self.assertEqual(d["label"], "a")

    def test_bundle_serialises(self) -> None:
        p = sp.ScenarioPlanner()
        spec = sp.ScenarioSpec(
            name="s",
            starting_state={},
            branches=[sp.Branch(label="a", weight=1.0)],
        )
        d = p.plan(spec).as_dict()
        self.assertIn("scenarios", d)


if __name__ == "__main__":
    unittest.main()
