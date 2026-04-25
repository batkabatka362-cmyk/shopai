"""Hyperparameter tuner tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import hyperparameter_tuner as hp


class TestRegister(unittest.TestCase):
    def test_register_returns_knob(self) -> None:
        t = hp.HyperparameterTuner()
        k = t.register("kill_threshold", arms=[1.2, 1.5, 1.8])
        self.assertEqual(len(k.arms), 3)

    def test_blank_name_raises(self) -> None:
        t = hp.HyperparameterTuner()
        with self.assertRaises(ValueError):
            t.register("", arms=[1])

    def test_no_arms_raises(self) -> None:
        t = hp.HyperparameterTuner()
        with self.assertRaises(ValueError):
            t.register("x", arms=[])

    def test_duplicate_raises_unless_overwrite(self) -> None:
        t = hp.HyperparameterTuner()
        t.register("k", arms=[1])
        with self.assertRaises(ValueError):
            t.register("k", arms=[2])
        t.register("k", arms=[3], overwrite=True)
        self.assertEqual(t.get("k").arms[0].value, 3)

    def test_unregister(self) -> None:
        t = hp.HyperparameterTuner()
        t.register("k", arms=[1])
        self.assertTrue(t.unregister("k"))
        self.assertFalse(t.unregister("k"))


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self.t = hp.HyperparameterTuner()
        self.t.register("k", arms=[1.0, 2.0])

    def test_observe_updates(self) -> None:
        self.t.observe("k", arm=1.0, reward=10.0, success=True)
        arm = self.t.get("k").arm(1.0)
        self.assertEqual(arm.pulls, 1)
        self.assertEqual(arm.wins, 1)
        self.assertAlmostEqual(arm.reward_mean, 10.0)

    def test_observe_running_mean(self) -> None:
        self.t.observe("k", arm=1.0, reward=10.0)
        self.t.observe("k", arm=1.0, reward=20.0)
        arm = self.t.get("k").arm(1.0)
        self.assertAlmostEqual(arm.reward_mean, 15.0)

    def test_observe_unknown_knob_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.observe("nope", arm=1.0)

    def test_observe_unknown_arm_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.observe("k", arm=999)

    def test_failure_does_not_count_as_win(self) -> None:
        self.t.observe("k", arm=1.0, reward=0, success=False)
        arm = self.t.get("k").arm(1.0)
        self.assertEqual(arm.pulls, 1)
        self.assertEqual(arm.wins, 0)


class TestSuggestExplore(unittest.TestCase):
    def setUp(self) -> None:
        self.t = hp.HyperparameterTuner()
        self.t.register("k", arms=["a", "b", "c"])

    def test_unseen_arm_suggested_first(self) -> None:
        self.t.observe("k", arm="a", reward=10, success=True)
        # b and c are unseen → next suggest should be b
        self.assertEqual(self.t.suggest("k"), "b")

    def test_explore_off_returns_best_anyway(self) -> None:
        self.t.observe("k", arm="a", reward=10, success=True)
        # explore_unseen=False → no obligation to try b/c
        s = self.t.suggest("k", explore_unseen=False)
        self.assertEqual(s, "a")


class TestSuggestExploit(unittest.TestCase):
    def test_pick_arm_with_highest_payoff_x_rate(self) -> None:
        t = hp.HyperparameterTuner()
        t.register("k", arms=["a", "b"])
        for _ in range(5):
            t.observe("k", arm="a", reward=10, success=True)
        for _ in range(5):
            t.observe("k", arm="b", reward=2, success=True)
        # All arms now seen — best should be "a"
        self.assertEqual(
            t.suggest("k", explore_unseen=False), "a",
        )

    def test_safe_policy_prefers_success_rate(self) -> None:
        t = hp.HyperparameterTuner()
        t.register("k", arms=["risky", "safe"])
        # risky: huge reward but only 1/10 wins
        t.observe("k", arm="risky", reward=100, success=True)
        for _ in range(9):
            t.observe("k", arm="risky", reward=0, success=False)
        # safe: small reward but 9/10 wins
        for _ in range(9):
            t.observe("k", arm="safe", reward=2, success=True)
        t.observe("k", arm="safe", reward=0, success=False)
        # "best" picks risky (huge mean × 0.1 ≈ 1.0 vs safe ≈ 1.62)
        # Both safe and best may pick safe; explicitly check safe
        self.assertEqual(
            t.suggest("k", policy="safe", explore_unseen=False),
            "safe",
        )


class TestBestArm(unittest.TestCase):
    def test_best_arm_returns_pulled_only(self) -> None:
        t = hp.HyperparameterTuner()
        t.register("k", arms=["a", "b"])
        # Nothing observed → no best arm
        self.assertIsNone(t.best_arm("k"))
        t.observe("k", arm="a", reward=5, success=True)
        self.assertEqual(t.best_arm("k").value, "a")

    def test_unknown_knob_returns_none(self) -> None:
        t = hp.HyperparameterTuner()
        self.assertIsNone(t.best_arm("nope"))


class TestPersistence(unittest.TestCase):
    def test_replay_from_disk(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "h.db"
        first = hp.HyperparameterTuner(db_path=path)
        first.register("k", arms=[1.0, 2.0])
        for _ in range(3):
            first.observe("k", arm=1.0, reward=10, success=True)
        first.close()
        second = hp.HyperparameterTuner(db_path=path)
        second.register("k", arms=[1.0, 2.0])
        arm = second.get("k").arm(1.0)
        # Observations replayed on register
        self.assertEqual(arm.pulls, 3)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        t = hp.HyperparameterTuner()
        t.register("k", arms=[1, 2])
        t.observe("k", arm=1, reward=1, success=True)
        s = t.stats()
        self.assertEqual(s["knobs"], 1)
        self.assertEqual(s["by_knob"]["k"]["arms"], 2)
        self.assertEqual(s["by_knob"]["k"]["pulls"], 1)


class TestReset(unittest.TestCase):
    def test_reset_single(self) -> None:
        t = hp.HyperparameterTuner()
        t.register("a", arms=[1])
        t.register("b", arms=[1])
        t.observe("a", arm=1, reward=1)
        t.observe("b", arm=1, reward=1)
        n = t.reset("a")
        self.assertEqual(n, 1)
        self.assertEqual(t.get("a").arm(1).pulls, 0)
        self.assertEqual(t.get("b").arm(1).pulls, 1)

    def test_reset_all(self) -> None:
        t = hp.HyperparameterTuner()
        t.register("a", arms=[1])
        t.observe("a", arm=1)
        t.reset()
        self.assertEqual(t.get("a").arm(1).pulls, 0)


class TestDict(unittest.TestCase):
    def test_arm_and_knob_serialise(self) -> None:
        t = hp.HyperparameterTuner()
        k = t.register("k", arms=[1.5])
        t.observe("k", arm=1.5, reward=2, success=True)
        d = k.as_dict()
        self.assertEqual(d["name"], "k")
        self.assertIn("success_rate", d["arms"][0])


if __name__ == "__main__":
    unittest.main()
