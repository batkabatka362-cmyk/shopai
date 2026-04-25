"""A/B bandit tests."""
from __future__ import annotations

import random
import tempfile
import unittest
from pathlib import Path

from core.brain import ab_bandit as ab


class TestCreate(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.b = ab.ABBandit(
            Path(self._tmp.name) / "b.db", rng=random.Random(0),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_create_experiment(self) -> None:
        exp = self.b.create("exp_1", ["A", "B"])
        self.assertEqual(exp.status, "active")
        self.assertEqual(len(exp.arms), 2)

    def test_duplicate_overwrites(self) -> None:
        self.b.create("exp_1", ["A", "B"])
        exp = self.b.create("exp_1", ["X", "Y", "Z"])
        self.assertEqual(len(exp.arms), 3)

    def test_blank_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.create("", ["A", "B"])

    def test_single_arm_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.create("x", ["A"])


class TestAssign(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.b = ab.ABBandit(
            Path(self._tmp.name) / "b.db", rng=random.Random(42),
        )
        self.b.create("e", ["A", "B", "C"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_assign_returns_one_of_arms(self) -> None:
        aid = self.b.assign("e")
        self.assertIn(aid, ("A", "B", "C"))

    def test_assignments_counter_increments(self) -> None:
        for _ in range(10):
            self.b.assign("e")
        exp = self.b.get("e")
        total = sum(a.assignments for a in exp.arms)
        self.assertEqual(total, 10)

    def test_unknown_exp_returns_none(self) -> None:
        self.assertIsNone(self.b.assign("nope"))


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.b = ab.ABBandit(Path(self._tmp.name) / "b.db")
        self.b.create("e", ["A", "B"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_success_raises_alpha(self) -> None:
        self.assertTrue(self.b.record("e", "A", success=True))
        exp = self.b.get("e")
        arm = exp.arm("A")
        self.assertGreater(arm.alpha, 1.0)

    def test_failure_raises_beta(self) -> None:
        self.b.record("e", "A", success=False)
        arm = self.b.get("e").arm("A")
        self.assertGreater(arm.beta, 1.0)

    def test_unknown_arm_returns_false(self) -> None:
        self.assertFalse(self.b.record("e", "NOPE", success=True))


class TestLearning(unittest.TestCase):
    def test_bandit_converges_on_winner(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        b = ab.ABBandit(
            Path(tmp.name) / "b.db", rng=random.Random(7),
        )
        b.create("e", ["good", "bad"])
        # Simulate: good succeeds 80%, bad 20%
        rng = random.Random(123)
        for _ in range(200):
            arm = b.assign("e")
            if arm == "good":
                b.record("e", arm, success=(rng.random() < 0.8))
            else:
                b.record("e", arm, success=(rng.random() < 0.2))
        leader = b.leader("e")
        self.assertEqual(leader.arm_id, "good")
        # Should allocate more traffic to the winner
        exp = b.get("e")
        self.assertGreater(
            exp.arm("good").assignments,
            exp.arm("bad").assignments,
        )
        tmp.cleanup()


class TestSignificance(unittest.TestCase):
    def test_lopsided_arms_have_high_probability(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        b = ab.ABBandit(
            Path(tmp.name) / "b.db", rng=random.Random(1),
        )
        b.create("e", ["A", "B"])
        for _ in range(50):
            b.record("e", "A", success=True)
        for _ in range(50):
            b.record("e", "B", success=False)
        sig = b.significance("e", draws=500)
        self.assertGreater(sig["A"], 0.9)
        self.assertLess(sig["B"], 0.1)
        tmp.cleanup()

    def test_unknown_experiment_empty(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        b = ab.ABBandit(Path(tmp.name) / "b.db")
        self.assertEqual(b.significance("nope"), {})
        tmp.cleanup()


class TestArchive(unittest.TestCase):
    def test_archive_sets_winner_and_stops_assigning(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        b = ab.ABBandit(Path(tmp.name) / "b.db")
        b.create("e", ["A", "B"])
        for _ in range(5):
            b.record("e", "A", success=True)
        self.assertTrue(b.archive("e"))
        exp = b.get("e")
        self.assertEqual(exp.status, "archived")
        self.assertEqual(exp.winner_id, "A")
        # No longer assigns
        self.assertIsNone(b.assign("e"))
        tmp.cleanup()

    def test_archive_unknown_returns_false(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        b = ab.ABBandit(Path(tmp.name) / "b.db")
        self.assertFalse(b.archive("missing"))
        tmp.cleanup()


class TestActiveListing(unittest.TestCase):
    def test_active_experiments_excludes_archived(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        b = ab.ABBandit(Path(tmp.name) / "b.db")
        b.create("live", ["A", "B"])
        b.create("dead", ["A", "B"])
        b.archive("dead", winner_id="A")
        active = b.active_experiments()
        ids = [e.id for e in active]
        self.assertIn("live", ids)
        self.assertNotIn("dead", ids)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
