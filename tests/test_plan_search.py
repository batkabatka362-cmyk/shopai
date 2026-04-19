"""Plan search tests."""
from __future__ import annotations

import unittest

from core.brain import plan_search as ps


def _set(key: str, value):
    def fn(s):
        out = dict(s)
        out[key] = value
        return out
    return fn


class TestTrivial(unittest.TestCase):
    def test_goal_already_met_zero_cost(self) -> None:
        plan = ps.search(
            start={"x": 1},
            goal_fn=ps.predicate_goal({"x": 1}),
            actions=[],
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.cost, 0.0)
        self.assertEqual(plan.actions, [])

    def test_no_actions_and_goal_unmet(self) -> None:
        plan = ps.search(
            start={"x": 1},
            goal_fn=ps.predicate_goal({"x": 2}),
            actions=[],
        )
        self.assertIsNone(plan)


class TestSingleStep(unittest.TestCase):
    def test_one_action_reaches_goal(self) -> None:
        actions = [ps.Action(
            name="set_x_2",
            preconditions=lambda s: True,
            effects=_set("x", 2),
            cost=1.0,
        )]
        plan = ps.search(
            start={"x": 1},
            goal_fn=ps.predicate_goal({"x": 2}),
            actions=actions,
        )
        self.assertEqual(plan.actions, ["set_x_2"])
        self.assertEqual(plan.cost, 1.0)


class TestChain(unittest.TestCase):
    def test_two_step_chain(self) -> None:
        actions = [
            ps.Action(
                name="ingest",
                preconditions=lambda s: not s.get("ingested"),
                effects=_set("ingested", True),
                cost=1.0,
            ),
            ps.Action(
                name="publish",
                preconditions=lambda s: s.get("ingested"),
                effects=_set("published", True),
                cost=1.0,
            ),
        ]
        plan = ps.search(
            start={},
            goal_fn=ps.predicate_goal({"published": True}),
            actions=actions,
        )
        self.assertEqual(plan.actions, ["ingest", "publish"])
        self.assertEqual(plan.cost, 2.0)

    def test_prefers_lower_cost_path(self) -> None:
        # Two ways to get published: direct (cost 5) vs via staging (1+1)
        actions = [
            ps.Action(
                name="direct",
                preconditions=lambda s: True,
                effects=_set("published", True),
                cost=5.0,
            ),
            ps.Action(
                name="stage",
                preconditions=lambda s: not s.get("staged"),
                effects=_set("staged", True),
                cost=1.0,
            ),
            ps.Action(
                name="release",
                preconditions=lambda s: s.get("staged"),
                effects=_set("published", True),
                cost=1.0,
            ),
        ]
        plan = ps.search(
            start={},
            goal_fn=ps.predicate_goal({"published": True}),
            actions=actions,
        )
        self.assertEqual(plan.actions, ["stage", "release"])
        self.assertEqual(plan.cost, 2.0)


class TestHeuristic(unittest.TestCase):
    def test_delta_heuristic_admissible(self) -> None:
        actions = [
            ps.Action(
                name="ingest",
                preconditions=lambda s: True,
                effects=_set("a", True), cost=1.0,
            ),
            ps.Action(
                name="publish",
                preconditions=lambda s: s.get("a"),
                effects=_set("b", True), cost=1.0,
            ),
        ]
        target = {"a": True, "b": True}
        plan = ps.search(
            start={},
            goal_fn=ps.predicate_goal(target),
            actions=actions,
            heuristic=ps.delta_heuristic(target),
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.cost, 2.0)


class TestBudget(unittest.TestCase):
    def test_expansion_budget_aborts(self) -> None:
        # Unreachable goal but many applicable actions
        actions = [
            ps.Action(
                name=f"flip_{i}",
                preconditions=lambda s, i=i: True,
                effects=_set(f"flag_{i}", True),
                cost=1.0,
            )
            for i in range(5)
        ]
        plan = ps.search(
            start={},
            goal_fn=ps.predicate_goal({"unreachable": True}),
            actions=actions,
            max_expansions=20,
        )
        self.assertIsNone(plan)

    def test_max_plan_length(self) -> None:
        # Allow unlimited expansions but cap plan length
        actions = [
            ps.Action(
                name=f"step_{i}",
                preconditions=lambda s, i=i: s.get("k") == i,
                effects=_set("k", i + 1),
                cost=1.0,
            )
            for i in range(10)
        ]
        plan = ps.search(
            start={"k": 0},
            goal_fn=ps.predicate_goal({"k": 10}),
            actions=actions,
            max_plan_length=5,
        )
        self.assertIsNone(plan)


class TestPreconditionRaises(unittest.TestCase):
    def test_raising_precondition_treated_false(self) -> None:
        def boom(_s):
            raise RuntimeError("x")

        actions = [
            ps.Action(
                name="bad", preconditions=boom,
                effects=_set("x", 1), cost=1.0,
            ),
            ps.Action(
                name="good", preconditions=lambda s: True,
                effects=_set("x", 1), cost=1.0,
            ),
        ]
        plan = ps.search(
            start={},
            goal_fn=ps.predicate_goal({"x": 1}),
            actions=actions,
        )
        self.assertEqual(plan.actions, ["good"])


class TestState(unittest.TestCase):
    def test_nested_dict_hashable(self) -> None:
        state = {"x": {"a": 1, "b": [1, 2, 3]}, "s": {1, 2}}
        frozen = ps._freeze(state)
        # Must be hashable — insertion into a set tests this
        self.assertIsInstance(hash(frozen), int)


class TestDict(unittest.TestCase):
    def test_plan_as_dict(self) -> None:
        p = ps.Plan(actions=["a", "b"], cost=2.0, expansions=5)
        d = p.as_dict()
        self.assertEqual(d["length"], 2)
        self.assertEqual(d["cost"], 2.0)


if __name__ == "__main__":
    unittest.main()
