"""Utility blender tests."""
from __future__ import annotations

import unittest

from core.brain import utility_blender as ub


class TestObjective(unittest.TestCase):
    def test_normalise_max(self) -> None:
        o = ub.Objective("x", direction="max", low=0, high=10)
        self.assertEqual(o.normalise(0), 0.0)
        self.assertEqual(o.normalise(10), 1.0)
        self.assertEqual(o.normalise(5), 0.5)

    def test_normalise_min(self) -> None:
        o = ub.Objective("x", direction="min", low=0, high=10)
        self.assertEqual(o.normalise(0), 1.0)
        self.assertEqual(o.normalise(10), 0.0)

    def test_normalise_clamps(self) -> None:
        o = ub.Objective("x", low=0, high=10)
        self.assertEqual(o.normalise(-5), 0.0)
        self.assertEqual(o.normalise(100), 1.0)

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            ub.Objective(name="", low=0, high=1)

    def test_equal_low_high_raises(self) -> None:
        with self.assertRaises(ValueError):
            ub.Objective("x", low=5, high=5)

    def test_negative_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            ub.Objective("x", weight=-1, low=0, high=1)

    def test_bad_direction_raises(self) -> None:
        with self.assertRaises(ValueError):
            ub.Objective("x", direction="wrong", low=0, high=1)


class TestFloor(unittest.TestCase):
    def test_floor_max_triggers_below(self) -> None:
        o = ub.Objective("roas", direction="max",
                          low=0, high=5, floor=1.5)
        self.assertTrue(o.violates_floor(1.4))
        self.assertFalse(o.violates_floor(1.6))

    def test_floor_min_triggers_above(self) -> None:
        o = ub.Objective("refund_rate", direction="min",
                          low=0, high=0.3, floor=0.1)
        self.assertTrue(o.violates_floor(0.15))
        self.assertFalse(o.violates_floor(0.05))


class TestBlender(unittest.TestCase):
    def setUp(self) -> None:
        self.b = ub.UtilityBlender()
        self.b.register(ub.Objective(
            "roas", direction="max", weight=2.0,
            low=0, high=5,
        ))
        self.b.register(ub.Objective(
            "refund_rate", direction="min", weight=1.0,
            low=0, high=0.3,
        ))

    def test_higher_weight_dominates(self) -> None:
        good_roas = self.b.score({"roas": 5, "refund_rate": 0.3})
        bad_roas = self.b.score({"roas": 0, "refund_rate": 0.0})
        # With weight 2× on roas, top roas should beat 0 refunds
        self.assertGreater(good_roas.score, bad_roas.score)

    def test_missing_value_zero_default(self) -> None:
        r = self.b.score({"roas": 5})  # refund_rate missing
        # Missing min-direction falls back to high → utility 0 on that obj
        self.assertGreater(r.score, 0.0)

    def test_missing_skip_policy(self) -> None:
        r = self.b.score({"roas": 5}, missing_policy="skip")
        self.assertNotIn("refund_rate", r.weighted_components)

    def test_missing_raise_policy(self) -> None:
        with self.assertRaises(KeyError):
            self.b.score({"roas": 5}, missing_policy="raise")

    def test_empty_blender_zero(self) -> None:
        empty = ub.UtilityBlender()
        self.assertEqual(
            empty.score({"x": 1}).score, 0.0,
        )


class TestRank(unittest.TestCase):
    def test_rank_sorts_desc(self) -> None:
        b = ub.UtilityBlender()
        b.register(ub.Objective("x", low=0, high=10))
        ranked = b.rank([
            {"name": "low", "values": {"x": 1}},
            {"name": "mid", "values": {"x": 5}},
            {"name": "high", "values": {"x": 9}},
        ])
        self.assertEqual([r[0] for r in ranked], ["high", "mid", "low"])


class TestFloorKillsScore(unittest.TestCase):
    def test_floor_violation_zeros_score(self) -> None:
        b = ub.UtilityBlender()
        b.register(ub.Objective(
            "roas", direction="max", low=0, high=5, floor=1.5,
        ))
        b.register(ub.Objective(
            "profit", direction="max", low=0, high=100,
        ))
        r = b.score({"roas": 1.0, "profit": 100})
        self.assertEqual(r.score, 0.0)
        self.assertIn("roas", r.floor_violations)


class TestRegistry(unittest.TestCase):
    def test_duplicate_rejected(self) -> None:
        b = ub.UtilityBlender()
        b.register(ub.Objective("x", low=0, high=1))
        with self.assertRaises(ValueError):
            b.register(ub.Objective("x", low=0, high=1))

    def test_overwrite_allowed(self) -> None:
        b = ub.UtilityBlender()
        b.register(ub.Objective("x", low=0, high=1, weight=1))
        b.register(
            ub.Objective("x", low=0, high=1, weight=2), overwrite=True,
        )
        self.assertEqual(b.objectives()[0].weight, 2)

    def test_unregister(self) -> None:
        b = ub.UtilityBlender()
        b.register(ub.Objective("x", low=0, high=1))
        self.assertTrue(b.unregister("x"))
        self.assertFalse(b.unregister("x"))


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        b = ub.UtilityBlender()
        b.register(ub.Objective("x", low=0, high=10, weight=1))
        r = b.score({"x": 5})
        d = r.as_dict()
        self.assertIn("score", d)
        self.assertIn("weighted_components", d)


if __name__ == "__main__":
    unittest.main()
