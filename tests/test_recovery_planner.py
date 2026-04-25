"""Recovery planner tests."""
from __future__ import annotations

import unittest

from core.brain import recovery_planner as rp


class TestPlaybook(unittest.TestCase):
    def test_blank_invariant_raises(self) -> None:
        with self.assertRaises(ValueError):
            rp.RecoveryPlaybook(invariant="", name="x", steps=["y"])

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            rp.RecoveryPlaybook(invariant="a", name="", steps=["y"])

    def test_no_steps_raises(self) -> None:
        with self.assertRaises(ValueError):
            rp.RecoveryPlaybook(invariant="a", name="x", steps=[])

    def test_invalid_blast_raises(self) -> None:
        with self.assertRaises(ValueError):
            rp.RecoveryPlaybook(
                invariant="a", name="x", steps=["y"], blast_radius=0,
            )

    def test_invalid_cost_raises(self) -> None:
        with self.assertRaises(ValueError):
            rp.RecoveryPlaybook(
                invariant="a", name="x", steps=["y"], cost_usd=-1,
            )

    def test_invalid_confidence_raises(self) -> None:
        with self.assertRaises(ValueError):
            rp.RecoveryPlaybook(
                invariant="a", name="x", steps=["y"], confidence=2.0,
            )

    def test_applies_to_empty_preconditions(self) -> None:
        p = rp.RecoveryPlaybook(
            invariant="a", name="x", steps=["y"],
        )
        self.assertTrue(p.applies_to({}))
        self.assertTrue(p.applies_to({"anything": "value"}))

    def test_applies_to_with_preconditions(self) -> None:
        p = rp.RecoveryPlaybook(
            invariant="a", name="x", steps=["y"],
            preconditions={"store": "us"},
        )
        self.assertTrue(p.applies_to({"store": "us"}))
        self.assertFalse(p.applies_to({"store": "eu"}))


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.p = rp.RecoveryPlanner()
        self.p.register(rp.RecoveryPlaybook(
            invariant="inv", name="a", steps=["restore"],
            confidence=0.8, blast_radius=1, priority=5,
        ))
        self.p.register(rp.RecoveryPlaybook(
            invariant="inv", name="b", steps=["nuke"],
            confidence=0.9, blast_radius=10, priority=1,
        ))

    def test_playbooks_filters_by_invariant(self) -> None:
        self.assertEqual(len(self.p.playbooks("inv")), 2)
        self.assertEqual(self.p.playbooks("other"), [])

    def test_unregister(self) -> None:
        self.assertTrue(self.p.unregister("inv", "a"))
        self.assertFalse(self.p.unregister("inv", "a"))


class TestPlanForBreach(unittest.TestCase):
    def test_low_blast_wins(self) -> None:
        p = rp.RecoveryPlanner()
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="narrow", steps=["x"],
            confidence=0.8, blast_radius=1,
        ))
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="wide", steps=["y"],
            confidence=0.8, blast_radius=50,
        ))
        ranked = p.plan_for_breach("i")
        self.assertEqual(ranked[0].playbook.name, "narrow")

    def test_higher_priority_wins_ties(self) -> None:
        p = rp.RecoveryPlanner()
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="low_pri", steps=["x"],
            confidence=0.8, blast_radius=1, priority=0,
        ))
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="high_pri", steps=["x"],
            confidence=0.8, blast_radius=1, priority=10,
        ))
        ranked = p.plan_for_breach("i")
        self.assertEqual(ranked[0].playbook.name, "high_pri")

    def test_preconditions_filter(self) -> None:
        p = rp.RecoveryPlanner()
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="us_only", steps=["x"],
            preconditions={"store": "us"},
        ))
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="eu_only", steps=["x"],
            preconditions={"store": "eu"},
        ))
        ranked = p.plan_for_breach("i", context={"store": "us"})
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0].playbook.name, "us_only")

    def test_empty_for_unknown_invariant(self) -> None:
        p = rp.RecoveryPlanner()
        self.assertEqual(p.plan_for_breach("never_happened"), [])

    def test_blank_invariant_raises(self) -> None:
        p = rp.RecoveryPlanner()
        with self.assertRaises(ValueError):
            p.plan_for_breach("")

    def test_top_k_invalid_raises(self) -> None:
        p = rp.RecoveryPlanner()
        with self.assertRaises(ValueError):
            p.plan_for_breach("i", top_k=0)


class TestBest(unittest.TestCase):
    def test_best_returns_top_or_none(self) -> None:
        p = rp.RecoveryPlanner()
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="only", steps=["x"],
        ))
        self.assertEqual(p.best_for_breach("i").playbook.name, "only")
        self.assertIsNone(p.best_for_breach("other"))


class TestConfig(unittest.TestCase):
    def test_negative_weights_raise(self) -> None:
        with self.assertRaises(ValueError):
            rp.RecoveryPlanner(blast_penalty=-1)


class TestCostPenalty(unittest.TestCase):
    def test_lower_cost_preferred(self) -> None:
        p = rp.RecoveryPlanner()
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="cheap", steps=["x"],
            confidence=0.8, cost_usd=0,
        ))
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="pricey", steps=["x"],
            confidence=0.8, cost_usd=500,
        ))
        ranked = p.plan_for_breach("i")
        self.assertEqual(ranked[0].playbook.name, "cheap")


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        p = rp.RecoveryPlanner()
        p.register(rp.RecoveryPlaybook(
            invariant="a", name="x", steps=["y"],
        ))
        p.register(rp.RecoveryPlaybook(
            invariant="b", name="x", steps=["y"],
        ))
        s = p.stats()
        self.assertEqual(s["playbooks"], 2)
        self.assertEqual(s["invariants_covered"], 2)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        pb = rp.RecoveryPlaybook(
            invariant="i", name="x", steps=["y"],
            tags=("t",),
        )
        d = pb.as_dict()
        self.assertEqual(d["name"], "x")
        self.assertEqual(d["tags"], ["t"])

    def test_ranked_serialises(self) -> None:
        p = rp.RecoveryPlanner()
        p.register(rp.RecoveryPlaybook(
            invariant="i", name="x", steps=["y"],
        ))
        d = p.plan_for_breach("i")[0].as_dict()
        self.assertIn("score", d)
        self.assertIn("why", d)


if __name__ == "__main__":
    unittest.main()
