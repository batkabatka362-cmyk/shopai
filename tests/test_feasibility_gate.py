"""Feasibility gate tests."""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from core.brain import feasibility_gate as fg


@dataclass
class AdAction:
    name: str
    cost: float
    margin: float = 0.2


class TestConstraint(unittest.TestCase):
    def test_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            fg.Constraint(name="", predicate=lambda a: True)

    def test_bad_severity_raises(self) -> None:
        with self.assertRaises(ValueError):
            fg.Constraint(
                name="x", predicate=lambda a: True, severity="oops",
            )

    def test_check_catches_raising_predicate(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        c = fg.Constraint(name="c", predicate=boom)
        self.assertFalse(c.check("anything"))


class TestBudgetCap(unittest.TestCase):
    def test_under_limit_feasible(self) -> None:
        c = fg.budget_cap("b", limit=10, extractor=lambda a: a.cost)
        self.assertTrue(c.check(AdAction("a", cost=5)))

    def test_over_limit_infeasible(self) -> None:
        c = fg.budget_cap("b", limit=10, extractor=lambda a: a.cost)
        self.assertFalse(c.check(AdAction("a", cost=20)))

    def test_negative_limit_raises(self) -> None:
        with self.assertRaises(ValueError):
            fg.budget_cap("b", limit=-1, extractor=lambda a: a.cost)


class TestFloorCap(unittest.TestCase):
    def test_above_floor_feasible(self) -> None:
        c = fg.floor_cap("f", floor=0.15, extractor=lambda a: a.margin)
        self.assertTrue(c.check(AdAction("a", cost=1, margin=0.2)))

    def test_below_floor_infeasible(self) -> None:
        c = fg.floor_cap("f", floor=0.15, extractor=lambda a: a.margin)
        self.assertFalse(c.check(AdAction("a", cost=1, margin=0.05)))


class TestInventoryCap(unittest.TestCase):
    def test_within_stock(self) -> None:
        c = fg.inventory_cap(
            "sku1", on_hand=10, extractor=lambda a: a["qty"],
        )
        self.assertTrue(c.check({"qty": 5}))

    def test_over_stock(self) -> None:
        c = fg.inventory_cap(
            "sku1", on_hand=10, extractor=lambda a: a["qty"],
        )
        self.assertFalse(c.check({"qty": 15}))

    def test_negative_on_hand_raises(self) -> None:
        with self.assertRaises(ValueError):
            fg.inventory_cap(
                "x", on_hand=-1, extractor=lambda a: 0,
            )


class TestValueIn(unittest.TestCase):
    def test_allowed(self) -> None:
        c = fg.value_in(
            "env", extractor=lambda a: a["env"],
            allowed=["dev", "prod"],
        )
        self.assertTrue(c.check({"env": "prod"}))

    def test_not_allowed(self) -> None:
        c = fg.value_in(
            "env", extractor=lambda a: a["env"],
            allowed=["dev", "prod"],
        )
        self.assertFalse(c.check({"env": "staging"}))


class TestGate(unittest.TestCase):
    def setUp(self) -> None:
        self.g = fg.FeasibilityGate()
        self.g.register(fg.budget_cap(
            "cost_cap", limit=10, extractor=lambda a: a.cost,
        ))
        self.g.register(fg.floor_cap(
            "margin_floor", floor=0.1, extractor=lambda a: a.margin,
        ))

    def test_all_feasible(self) -> None:
        v = self.g.evaluate(AdAction("ok", cost=5, margin=0.2))
        self.assertTrue(v.feasible)
        self.assertEqual(v.violations, [])

    def test_cost_over_blocks(self) -> None:
        v = self.g.evaluate(AdAction("bad", cost=20, margin=0.2))
        self.assertFalse(v.feasible)
        self.assertEqual(v.violations[0].constraint, "cost_cap")

    def test_soft_violation_still_feasible(self) -> None:
        g = fg.FeasibilityGate()
        g.register(fg.sla_cap(
            "latency", max_latency_ms=100,
            extractor=lambda a: a["ms"],
            severity="soft",
        ))
        v = g.evaluate({"ms": 500})
        self.assertTrue(v.feasible)   # soft, doesn't block
        self.assertEqual(len(v.violations), 1)

    def test_duplicate_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.g.register(fg.budget_cap(
                "cost_cap", limit=5,
                extractor=lambda a: a.cost,
            ))

    def test_overwrite_allowed(self) -> None:
        self.g.register(
            fg.budget_cap(
                "cost_cap", limit=999,
                extractor=lambda a: a.cost,
            ),
            overwrite=True,
        )
        self.assertTrue(self.g.evaluate(
            AdAction("bigspend", cost=500, margin=0.2),
        ).feasible)


class TestFilter(unittest.TestCase):
    def test_feasible_only(self) -> None:
        g = fg.FeasibilityGate()
        g.register(fg.budget_cap(
            "c", limit=10, extractor=lambda a: a.cost,
        ))
        actions = [
            AdAction("a", cost=5),
            AdAction("b", cost=15),
            AdAction("c", cost=8),
        ]
        feasible = g.feasible_only(actions)
        self.assertEqual([a.name for a in feasible], ["a", "c"])


class TestBestFeasible(unittest.TestCase):
    def test_picks_highest_feasible(self) -> None:
        g = fg.FeasibilityGate()
        g.register(fg.budget_cap(
            "c", limit=10, extractor=lambda a: a.cost,
        ))
        actions = [
            AdAction("cheap_ok", cost=5, margin=0.1),
            AdAction("bigger_ok", cost=9, margin=0.3),
            AdAction("over", cost=100, margin=0.99),
        ]
        best = g.best_feasible(actions, utility_fn=lambda a: a.margin)
        self.assertEqual(best.name, "bigger_ok")

    def test_no_feasible_returns_none(self) -> None:
        g = fg.FeasibilityGate()
        g.register(fg.budget_cap(
            "c", limit=0, extractor=lambda a: a.cost,
        ))
        actions = [AdAction("a", cost=1)]
        self.assertIsNone(g.best_feasible(actions, lambda a: 1.0))


class TestDict(unittest.TestCase):
    def test_verdict_serialises(self) -> None:
        g = fg.FeasibilityGate()
        g.register(fg.budget_cap(
            "c", limit=5, extractor=lambda a: a["cost"],
        ))
        v = g.evaluate({"cost": 50})
        d = v.as_dict()
        self.assertFalse(d["feasible"])
        self.assertEqual(len(d["violations"]), 1)


if __name__ == "__main__":
    unittest.main()
