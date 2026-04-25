"""Salience tuner tests."""
from __future__ import annotations

import unittest

from core.brain import salience_tuner as st


class TestConfig(unittest.TestCase):
    def test_bad_alpha_raises(self) -> None:
        with self.assertRaises(ValueError):
            st.SalienceTuner(ema_alpha=0)
        with self.assertRaises(ValueError):
            st.SalienceTuner(ema_alpha=1.5)


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self.t = st.SalienceTuner(ema_alpha=1.0)

    def test_empty_features_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.observe(
                features={}, outcome_importance=0.5,
            )

    def test_bad_importance_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.observe(
                features={"a": 1.0}, outcome_importance=1.5,
            )

    def test_predictive_feature_dominates(self) -> None:
        # "good" is present whenever outcome_importance high
        # "bad" is present whenever outcome_importance low
        for _ in range(20):
            self.t.observe(
                features={"good": 1.0, "bad": 0.0},
                outcome_importance=0.9,
            )
        for _ in range(20):
            self.t.observe(
                features={"good": 0.0, "bad": 1.0},
                outcome_importance=0.1,
            )
        w = self.t.weights()
        self.assertGreater(w["good"], w["bad"])

    def test_non_numeric_scores_skipped(self) -> None:
        self.t.observe(
            features={"good": 1.0, "weird": "oops"},
            outcome_importance=0.8,
        )
        w = self.t.weights()
        self.assertNotIn("weird", w)


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self) -> None:
        t = st.SalienceTuner(ema_alpha=1.0)
        for _ in range(5):
            t.observe(
                features={"a": 1.0, "b": 1.0},
                outcome_importance=0.8,
            )
        w = t.weights()
        total = sum(w.values())
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_recommend_zero_for_unknown(self) -> None:
        t = st.SalienceTuner()
        self.assertEqual(t.recommend_weight("nope"), 0.0)


class TestLowLift(unittest.TestCase):
    def test_low_lift_found(self) -> None:
        t = st.SalienceTuner(ema_alpha=1.0)
        for _ in range(10):
            t.observe(
                features={"noise": 1.0},
                outcome_importance=0.5,
            )
        low = t.low_lift_features(floor=0.1)
        self.assertIn("noise", low)


class TestEMASmoothing(unittest.TestCase):
    def test_single_observation_limited_by_alpha(self) -> None:
        # With alpha=0.2, a new dominant feature shouldn't instantly
        # take over the full weight.
        t = st.SalienceTuner(ema_alpha=0.2)
        for _ in range(5):
            t.observe(
                features={"a": 1.0, "b": 1.0},
                outcome_importance=0.5,
            )
        # Now one strong "c" signal
        t.observe(
            features={"c": 1.0, "a": 0.0, "b": 0.0},
            outcome_importance=0.9,
        )
        w = t.weights()
        # a/b still hold meaningful weight despite "c" looking great
        self.assertLess(w.get("c", 0.0), 0.9)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        t = st.SalienceTuner()
        t.observe(
            features={"a": 1.0}, outcome_importance=0.8,
        )
        s = t.stats()
        self.assertEqual(s["features"], 1)
        self.assertIn("top_weight", s)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        t = st.SalienceTuner()
        t.observe(
            features={"a": 1.0}, outcome_importance=0.5,
        )
        self.assertEqual(t.reset(), 1)


class TestDict(unittest.TestCase):
    def test_feature_stat_serialises(self) -> None:
        t = st.SalienceTuner()
        t.observe(
            features={"a": 1.0}, outcome_importance=0.8,
        )
        stats = t.feature_stats()
        d = stats[0].as_dict()
        self.assertIn("lift", d)


if __name__ == "__main__":
    unittest.main()
