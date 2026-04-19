"""Goal decomposer tests."""
from __future__ import annotations

import unittest

from core.brain import goal_decomposer as gd


class TestDecompose(unittest.TestCase):
    def setUp(self) -> None:
        self.d = gd.GoalDecomposer()

    def test_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.d.decompose("")

    def test_launch_sku(self) -> None:
        plan = self.d.decompose("launch new product")
        self.assertEqual(plan.rule_id, "launch_sku")
        # Expected 5 subgoals: create, media, price, publish, ad
        self.assertEqual(len(plan.subgoals), 5)
        names = [s.name for s in plan.subgoals]
        self.assertIn("create_product", names)
        self.assertIn("launch_ad", names)

    def test_launch_topological_order(self) -> None:
        plan = self.d.decompose("upload new sku")
        # Create must come before publish
        positions = {
            sid: i for i, sid in enumerate(plan.order)
        }
        self.assertLess(
            positions["sg_create"], positions["sg_publish"],
        )
        self.assertLess(
            positions["sg_publish"], positions["sg_ad"],
        )

    def test_revenue_target(self) -> None:
        plan = self.d.decompose(
            "hit $10,000 daily revenue",
            params={"target_revenue": 10000},
        )
        self.assertEqual(plan.rule_id, "revenue_target")

    def test_kill_rule(self) -> None:
        plan = self.d.decompose("kill ad when roas below 1.5")
        self.assertEqual(plan.rule_id, "kill_rule")
        kill = next(s for s in plan.subgoals if s.name == "auto_kill")
        self.assertIn("sg_watch", kill.depends_on)

    def test_unmatched_returns_placeholder(self) -> None:
        plan = self.d.decompose("philosophical question")
        self.assertEqual(plan.rule_id, "")
        self.assertEqual(len(plan.subgoals), 1)
        self.assertIn("no rule matched", plan.notes)


class TestCustomRule(unittest.TestCase):
    def test_register_and_run(self) -> None:
        def builder(goal_text, params):
            return [gd.SubGoal(
                id="sg_x", name="x", description=goal_text,
            )]

        rule = gd.DecompositionRule(
            id="custom",
            pattern=r"magic",
            builder=builder,
            priority=1,
        )
        d = gd.GoalDecomposer()
        d.register(rule)
        plan = d.decompose("perform magic")
        self.assertEqual(plan.rule_id, "custom")

    def test_unregister(self) -> None:
        d = gd.GoalDecomposer()
        self.assertTrue(d.unregister("launch_sku"))
        plan = d.decompose("launch product")
        # no rule now → placeholder
        self.assertEqual(plan.rule_id, "")


class TestToposort(unittest.TestCase):
    def test_cycle_raises(self) -> None:
        def builder(_g, _p):
            return [
                gd.SubGoal(
                    id="a", name="a", description="",
                    depends_on=("b",),
                ),
                gd.SubGoal(
                    id="b", name="b", description="",
                    depends_on=("a",),
                ),
            ]

        d = gd.GoalDecomposer(rules=[
            gd.DecompositionRule(
                id="cycl", pattern=r"cycle",
                builder=builder, priority=1,
            ),
        ])
        with self.assertRaises(ValueError):
            d.decompose("cycle")

    def test_unknown_dep_raises(self) -> None:
        def builder(_g, _p):
            return [
                gd.SubGoal(
                    id="a", name="a", description="",
                    depends_on=("ghost",),
                ),
            ]

        d = gd.GoalDecomposer(rules=[
            gd.DecompositionRule(
                id="bad", pattern=r"bad",
                builder=builder, priority=1,
            ),
        ])
        with self.assertRaises(ValueError):
            d.decompose("bad")


class TestQueries(unittest.TestCase):
    def test_rules_listing(self) -> None:
        d = gd.GoalDecomposer()
        rules = d.rules()
        self.assertGreater(len(rules), 0)
        self.assertTrue(
            any(r["id"] == "launch_sku" for r in rules),
        )

    def test_stats(self) -> None:
        d = gd.GoalDecomposer()
        s = d.stats()
        self.assertGreater(s["rules"], 0)
        self.assertIn("launch_sku", s["rule_ids"])


class TestDict(unittest.TestCase):
    def test_subgoal_serialises(self) -> None:
        s = gd.SubGoal(id="x", name="x", description="y")
        d = s.as_dict()
        self.assertEqual(d["name"], "x")
        self.assertEqual(d["depends_on"], [])

    def test_plan_serialises(self) -> None:
        d = gd.GoalDecomposer()
        plan = d.decompose("launch product")
        out = plan.as_dict()
        self.assertIn("subgoals", out)
        self.assertIn("order", out)


if __name__ == "__main__":
    unittest.main()
