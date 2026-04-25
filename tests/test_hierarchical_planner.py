"""Hierarchical planner — template + DAG shape tests."""
from __future__ import annotations

import unittest

from core.brain import hierarchical_planner as hp


class TestDecomposeRouting(unittest.TestCase):
    def test_revenue_template_has_three_weeks(self) -> None:
        h = hp.decompose("double revenue in 30 days")
        weeks = [n for n in h.nodes.values() if n.level == "subgoal"]
        self.assertEqual(len(weeks), 3)
        self.assertEqual(weeks[0].horizon_days, 7)

    def test_aov_template_uses_bundles_and_cross_sell(self) -> None:
        h = hp.decompose("lift AOV 15 % with upsell")
        titles = [n.title for n in h.nodes.values()]
        self.assertTrue(any("related_product_ids" in t for t in titles))
        self.assertTrue(any("bundles" in t for t in titles))

    def test_niche_test_template(self) -> None:
        h = hp.decompose("test a new pets niche")
        actions = [n for n in h.nodes.values() if n.level == "action"]
        self.assertTrue(all(a.params.get("kind") == "launch_product"
                            for a in actions))
        self.assertEqual(len(actions), 3)   # three probes

    def test_efficiency_cuts_losers_and_reuses_creative(self) -> None:
        h = hp.decompose("reduce spend 20% efficiency drive")
        titles = [n.title for n in h.nodes.values()]
        self.assertTrue(any("Kill under-performers" in t for t in titles))
        self.assertTrue(any("Reuse" in t for t in titles))

    def test_multi_store_clones_and_shares(self) -> None:
        h = hp.decompose("scale to 3 stores multi-store by Q4")
        titles = [n.title for n in h.nodes.values()]
        self.assertTrue(any("Share rules" in t for t in titles))
        self.assertTrue(any("Clone top winners" in t for t in titles))

    def test_generic_goal_falls_back_to_reasoner(self) -> None:
        h = hp.decompose("figure out what to do")
        kinds = [n.params.get("kind") for n in h.nodes.values()
                 if n.level == "action"]
        self.assertEqual(kinds, ["run_reasoning"])

    def test_empty_goal_returns_empty_hierarchy(self) -> None:
        h = hp.decompose("")
        self.assertEqual(h.nodes, {})
        self.assertEqual(h.root_id, "")


class TestHierarchyOps(unittest.TestCase):
    def test_children_and_leaves(self) -> None:
        h = hp.decompose("lift AOV")
        leaves = h.leaves()
        self.assertTrue(all(l.level == "action" for l in leaves))

    def test_total_budget_sums_action_costs(self) -> None:
        h = hp.decompose("test a new pets niche")
        self.assertAlmostEqual(h.total_budget(), 60.0 * 3, places=2)


class TestNodeShape(unittest.TestCase):
    def test_parent_and_children_linked(self) -> None:
        h = hp.decompose("lift AOV")
        sg = next(n for n in h.nodes.values() if n.level == "subgoal")
        root = h.nodes[h.root_id]
        self.assertIn(sg.id, root.children_ids)
        self.assertEqual(sg.parent_id, root.id)

    def test_as_dict_round_trip(self) -> None:
        import json
        h = hp.decompose("lift AOV")
        # Must be JSON-serialisable
        json.dumps(h.as_dict())


if __name__ == "__main__":
    unittest.main()
