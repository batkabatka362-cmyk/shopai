"""Exploration manager tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import exploration_manager as em


class TestRegister(unittest.TestCase):
    def test_register_single(self) -> None:
        m = em.ExplorationManager()
        m.register("b", arms=["a", "b", "c"])
        snap = m.snapshot("b")
        self.assertEqual(len(snap.arms), 3)

    def test_blank_name_raises(self) -> None:
        m = em.ExplorationManager()
        with self.assertRaises(ValueError):
            m.register("", arms=["a"])

    def test_no_arms_raises(self) -> None:
        m = em.ExplorationManager()
        with self.assertRaises(ValueError):
            m.register("b", arms=[])

    def test_invalid_strategy_raises(self) -> None:
        m = em.ExplorationManager()
        with self.assertRaises(ValueError):
            m.register("b", arms=["a"], strategy="foo")  # type: ignore

    def test_unregister(self) -> None:
        m = em.ExplorationManager()
        m.register("b", arms=["a"])
        self.assertTrue(m.unregister("b"))
        self.assertFalse(m.unregister("b"))


class TestEpsilonGreedy(unittest.TestCase):
    def test_zero_epsilon_picks_best(self) -> None:
        m = em.ExplorationManager(seed=0)
        m.register("b", arms=["a", "b"], strategy="epsilon_greedy")
        # Train a way ahead
        for _ in range(20):
            m.observe("b", "a", success=True)
        for _ in range(20):
            m.observe("b", "b", success=False)
        for _ in range(50):
            self.assertEqual(
                m.pick("b", strategy="epsilon_greedy", epsilon=0.0),
                "a",
            )

    def test_epsilon_one_explores(self) -> None:
        m = em.ExplorationManager(seed=42)
        m.register("b", arms=["a", "b"], strategy="epsilon_greedy")
        choices = {
            m.pick("b", strategy="epsilon_greedy", epsilon=1.0)
            for _ in range(50)
        }
        self.assertEqual(choices, {"a", "b"})


class TestThompson(unittest.TestCase):
    def test_thompson_eventually_finds_winner(self) -> None:
        m = em.ExplorationManager(seed=0)
        m.register("b", arms=["winner", "loser"])
        for _ in range(200):
            arm = m.pick("b")
            m.observe(
                "b", arm,
                success=(
                    arm == "winner" and m._rng.random() < 0.9
                    or arm == "loser" and m._rng.random() < 0.1
                ),
            )
        # Winner should have higher mean
        snap = m.snapshot("b")
        means = {a["name"]: a["mean"] for a in snap.arms}
        self.assertGreater(means["winner"], means["loser"])


class TestUCB1(unittest.TestCase):
    def test_ucb1_explores_unseen_first(self) -> None:
        m = em.ExplorationManager(seed=0)
        m.register("b", arms=["a", "b"], strategy="ucb1")
        # First pick: anything (both unseen)
        first = m.pick("b")
        m.observe("b", first, success=True)
        # Second pick: should be the OTHER arm (still unseen)
        second = m.pick("b")
        self.assertNotEqual(first, second)


class TestObserve(unittest.TestCase):
    def test_observe_updates_posterior(self) -> None:
        m = em.ExplorationManager()
        m.register("b", arms=["a"])
        m.observe("b", "a", success=True)
        snap = m.snapshot("b")
        self.assertEqual(snap.arms[0]["pulls"], 1)
        self.assertGreater(snap.arms[0]["mean"], 0.5)

    def test_observe_unknown_bandit_raises(self) -> None:
        m = em.ExplorationManager()
        with self.assertRaises(ValueError):
            m.observe("nope", "a", success=True)

    def test_observe_unknown_arm_raises(self) -> None:
        m = em.ExplorationManager()
        m.register("b", arms=["a"])
        with self.assertRaises(ValueError):
            m.observe("b", "nope", success=True)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "e.db"
        first = em.ExplorationManager(db_path=path)
        first.register("b", arms=["a"], strategy="ucb1")
        first.observe("b", "a", success=True)
        first.close()
        second = em.ExplorationManager(db_path=path)
        snap = second.snapshot("b")
        self.assertEqual(snap.arms[0]["pulls"], 1)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        m = em.ExplorationManager()
        m.register("b", arms=["a", "x"])
        m.observe("b", "a", success=True)
        m.observe("b", "x", success=False)
        s = m.stats()
        self.assertEqual(s["bandits"], 1)
        self.assertEqual(s["by_bandit"]["b"]["arms"], 2)
        self.assertEqual(s["by_bandit"]["b"]["total_pulls"], 2)


class TestDict(unittest.TestCase):
    def test_snapshot_serialises(self) -> None:
        m = em.ExplorationManager()
        m.register("b", arms=["a"])
        d = m.snapshot("b").as_dict()
        self.assertIn("arms", d)
        self.assertIn("strategy", d)


if __name__ == "__main__":
    unittest.main()
