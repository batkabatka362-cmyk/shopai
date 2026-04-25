"""Value weighter tests."""
from __future__ import annotations

import unittest

from core.brain import value_weighter as vw


class TestConfig(unittest.TestCase):
    def test_bad_lr_raises(self) -> None:
        with self.assertRaises(ValueError):
            vw.ValueWeighter(learning_rate=0)

    def test_bad_floor_raises(self) -> None:
        with self.assertRaises(ValueError):
            vw.ValueWeighter(floor=1.0)


class TestObserve(unittest.TestCase):
    def setUp(self) -> None:
        self.w = vw.ValueWeighter(learning_rate=0.5, floor=0.0)

    def test_bad_feedback_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.w.observe(
                value_scores={"revenue": 1.0},
                feedback="maybe",  # type: ignore[arg-type]
            )

    def test_empty_scores_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.w.observe(
                value_scores={}, feedback="approve",
            )

    def test_approve_raises_weight(self) -> None:
        self.w.observe(
            value_scores={"revenue": 1.0, "margin": 0.0},
            feedback="approve",
        )
        weights = self.w.weights()
        self.assertGreater(weights["revenue"], weights["margin"])

    def test_praise_stronger_than_approve(self) -> None:
        self.w.observe(
            value_scores={"revenue": 1.0},
            feedback="approve",
        )
        w1 = self.w.raw_weights()["revenue"]
        w2 = vw.ValueWeighter(
            learning_rate=0.5, floor=0.0,
        )
        w2.observe(
            value_scores={"revenue": 1.0},
            feedback="praise",
        )
        self.assertGreater(
            w2.raw_weights()["revenue"], w1,
        )

    def test_reject_lowers(self) -> None:
        self.w.observe(
            value_scores={"risk": 1.0},
            feedback="reject",
        )
        self.assertLess(self.w.raw_weights()["risk"], 0.0)

    def test_criticise_stronger_than_reject(self) -> None:
        w1 = vw.ValueWeighter(
            learning_rate=0.5, floor=0.0,
        )
        w1.observe(
            value_scores={"x": 1.0}, feedback="reject",
        )
        w2 = vw.ValueWeighter(
            learning_rate=0.5, floor=0.0,
        )
        w2.observe(
            value_scores={"x": 1.0}, feedback="criticise",
        )
        self.assertLess(
            w2.raw_weights()["x"],
            w1.raw_weights()["x"],
        )

    def test_non_numeric_skipped(self) -> None:
        self.w.observe(
            value_scores={"good": 1.0, "weird": "oops"},
            feedback="approve",
        )
        self.assertNotIn("weird", self.w.raw_weights())


class TestWeights(unittest.TestCase):
    def test_weights_normalised(self) -> None:
        w = vw.ValueWeighter()
        w.observe(
            value_scores={"a": 1.0, "b": 1.0},
            feedback="approve",
        )
        weights = w.weights()
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_empty_gives_uniform(self) -> None:
        w = vw.ValueWeighter()
        # Register values via a neutral observation
        w.observe(
            value_scores={"a": 0.0, "b": 0.0},
            feedback="approve",
        )
        weights = w.weights()
        self.assertAlmostEqual(
            weights["a"], weights["b"], places=3,
        )

    def test_floor_applied(self) -> None:
        w = vw.ValueWeighter(learning_rate=1.0, floor=0.1)
        # Heavily reject x
        for _ in range(10):
            w.observe(
                value_scores={"x": 1.0, "y": 0.0},
                feedback="criticise",
            )
            w.observe(
                value_scores={"x": 0.0, "y": 1.0},
                feedback="praise",
            )
        weights = w.weights()
        # Floor keeps x > 0 even under heavy criticism
        self.assertGreater(weights["x"], 0.0)


class TestQueries(unittest.TestCase):
    def test_trace(self) -> None:
        w = vw.ValueWeighter()
        w.observe(
            value_scores={"rev": 1.0},
            feedback="approve",
        )
        t = w.trace("rev")
        self.assertEqual(t.value, "rev")
        self.assertEqual(t.observation_count, 1)

    def test_trace_unknown(self) -> None:
        w = vw.ValueWeighter()
        self.assertIsNone(w.trace("nope"))

    def test_ranked(self) -> None:
        w = vw.ValueWeighter()
        w.observe(
            value_scores={"high": 1.0, "low": 0.1},
            feedback="approve",
        )
        r = w.ranked()
        self.assertEqual(r[0].value, "high")


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        w = vw.ValueWeighter()
        w.observe(
            value_scores={"x": 1.0},
            feedback="approve",
        )
        s = w.stats()
        self.assertEqual(s["values_tracked"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        w = vw.ValueWeighter()
        w.observe(
            value_scores={"x": 1.0},
            feedback="approve",
        )
        self.assertEqual(w.reset(), 1)


class TestDict(unittest.TestCase):
    def test_trace_serialises(self) -> None:
        w = vw.ValueWeighter()
        w.observe(
            value_scores={"x": 1.0},
            feedback="approve",
        )
        d = w.trace("x").as_dict()
        self.assertIn("weight", d)


if __name__ == "__main__":
    unittest.main()
