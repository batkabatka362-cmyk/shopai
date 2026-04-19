"""Constraint solver tests — greedy LP allocation."""
from __future__ import annotations

import unittest

from core.brain import constraint_solver as cs


class TestSolve(unittest.TestCase):
    def test_all_to_best_when_unconstrained(self) -> None:
        items = [
            cs.Item(id="a", marginal_roas=3.0, max_budget=200),
            cs.Item(id="b", marginal_roas=1.5, max_budget=200),
        ]
        alloc = cs.solve(items, total_budget=100)
        self.assertEqual(alloc.get("a").allocated, 100.0)
        self.assertEqual(alloc.get("b").allocated, 0.0)

    def test_respects_max_budget_cap(self) -> None:
        items = [
            cs.Item(id="a", marginal_roas=3.0, max_budget=50),
            cs.Item(id="b", marginal_roas=1.5, max_budget=200),
        ]
        alloc = cs.solve(items, total_budget=100)
        self.assertEqual(alloc.get("a").allocated, 50.0)
        self.assertEqual(alloc.get("a").binding, "max")
        self.assertEqual(alloc.get("b").allocated, 50.0)

    def test_inventory_cap_binds(self) -> None:
        # Item a has $10 marginal ROAS but only 5 units at 1 unit/$
        items = [
            cs.Item(id="a", marginal_roas=10.0, max_budget=200,
                     inventory_units=5, demand_per_dollar=1.0),
            cs.Item(id="b", marginal_roas=2.0, max_budget=200),
        ]
        alloc = cs.solve(items, total_budget=100)
        # a capped at inventory (5 units / 1 unit/$ = $5)
        self.assertAlmostEqual(alloc.get("a").allocated, 5.0)
        self.assertEqual(alloc.get("a").binding, "inventory")
        # b gets the remaining 95
        self.assertAlmostEqual(alloc.get("b").allocated, 95.0)

    def test_minimums_honoured(self) -> None:
        items = [
            cs.Item(id="a", marginal_roas=3.0, min_budget=20,
                     max_budget=50),
            cs.Item(id="b", marginal_roas=1.0, min_budget=30,
                     max_budget=100),
        ]
        alloc = cs.solve(items, total_budget=100)
        self.assertGreaterEqual(alloc.get("a").allocated, 20)
        self.assertGreaterEqual(alloc.get("b").allocated, 30)

    def test_minimums_exceed_budget_scales_down(self) -> None:
        items = [
            cs.Item(id="a", marginal_roas=3.0, min_budget=60),
            cs.Item(id="b", marginal_roas=2.0, min_budget=60),
        ]
        alloc = cs.solve(items, total_budget=100)
        self.assertTrue(alloc.approx)
        self.assertAlmostEqual(alloc.total_spent, 100.0)
        # Each scaled to 60 * (100/120) = 50
        self.assertAlmostEqual(alloc.get("a").allocated, 50.0)

    def test_empty_items_zero_spent(self) -> None:
        alloc = cs.solve([], total_budget=100)
        self.assertEqual(alloc.total_spent, 0.0)

    def test_zero_budget_zero_spent(self) -> None:
        items = [cs.Item(id="a", marginal_roas=3.0)]
        alloc = cs.solve(items, total_budget=0)
        self.assertEqual(alloc.total_spent, 0.0)

    def test_expected_return_computed(self) -> None:
        items = [
            cs.Item(id="a", marginal_roas=3.0, max_budget=100),
            cs.Item(id="b", marginal_roas=2.0, max_budget=100),
        ]
        alloc = cs.solve(items, total_budget=100)
        # All 100 goes to a at 3.0 → expected 300
        self.assertAlmostEqual(alloc.expected_return, 300.0)

    def test_budget_spills_when_all_items_capped(self) -> None:
        items = [
            cs.Item(id="a", marginal_roas=3.0, max_budget=30),
            cs.Item(id="b", marginal_roas=2.0, max_budget=30),
        ]
        alloc = cs.solve(items, total_budget=100)
        # Max spend is 60, leaving 40 unspent
        self.assertAlmostEqual(alloc.total_spent, 60.0)


class TestBindingConstraints(unittest.TestCase):
    def test_lists_binding_items(self) -> None:
        items = [
            cs.Item(id="a", marginal_roas=3.0, max_budget=50),
            cs.Item(id="b", marginal_roas=2.0, max_budget=200),
        ]
        alloc = cs.solve(items, total_budget=100)
        binding = cs.binding_constraints(alloc)
        self.assertIn("a.max", binding)

    def test_underutilised_budget_flagged(self) -> None:
        items = [
            cs.Item(id="a", marginal_roas=3.0, max_budget=30),
        ]
        alloc = cs.solve(items, total_budget=100)
        binding = cs.binding_constraints(alloc)
        self.assertIn("total_budget.underutilised", binding)


class TestExplain(unittest.TestCase):
    def test_explain_renders_summary_and_breakdown(self) -> None:
        items = [
            cs.Item(id="audio", marginal_roas=3.0, max_budget=50),
            cs.Item(id="fashion", marginal_roas=1.5, max_budget=200),
        ]
        alloc = cs.solve(items, total_budget=100)
        text = cs.explain(alloc)
        self.assertIn("audio", text)
        self.assertIn("fashion", text)
        self.assertIn("expected", text)


if __name__ == "__main__":
    unittest.main()
