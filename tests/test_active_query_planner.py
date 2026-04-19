"""Active query planner tests."""
from __future__ import annotations

import math
import unittest

from core.brain import active_query_planner as aqp


class TestEntropy(unittest.TestCase):
    def test_uniform_binary_is_one_bit(self) -> None:
        self.assertAlmostEqual(
            aqp.entropy({"a": 0.5, "b": 0.5}), 1.0,
        )

    def test_point_mass_is_zero(self) -> None:
        self.assertEqual(
            aqp.entropy({"a": 1.0, "b": 0.0}), 0.0,
        )

    def test_uniform_four_is_two_bits(self) -> None:
        self.assertAlmostEqual(
            aqp.entropy({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}),
            2.0,
        )

    def test_empty_is_zero(self) -> None:
        self.assertEqual(aqp.entropy({}), 0.0)


class TestPosterior(unittest.TestCase):
    def test_perfect_evidence_collapses(self) -> None:
        priors = {"h1": 0.5, "h2": 0.5}
        model = {
            "h1": {"yes": 1.0, "no": 0.0},
            "h2": {"yes": 0.0, "no": 1.0},
        }
        post = aqp._posterior_given_answer(priors, model, "yes")
        self.assertAlmostEqual(post["h1"], 1.0)
        self.assertAlmostEqual(post["h2"], 0.0)


class TestEIG(unittest.TestCase):
    def test_perfect_discriminator_gains_one_bit(self) -> None:
        priors = {"h1": 0.5, "h2": 0.5}
        model = {
            "h1": {"yes": 1.0, "no": 0.0},
            "h2": {"yes": 0.0, "no": 1.0},
        }
        eig = aqp.expected_info_gain(priors, model)
        self.assertAlmostEqual(eig, 1.0, places=4)

    def test_uninformative_query_zero_gain(self) -> None:
        priors = {"h1": 0.5, "h2": 0.5}
        # Same distribution regardless of hypothesis
        model = {
            "h1": {"yes": 0.5, "no": 0.5},
            "h2": {"yes": 0.5, "no": 0.5},
        }
        eig = aqp.expected_info_gain(priors, model)
        self.assertAlmostEqual(eig, 0.0, places=4)

    def test_partial_discriminator_positive_gain(self) -> None:
        priors = {"h1": 0.5, "h2": 0.5}
        model = {
            "h1": {"yes": 0.8, "no": 0.2},
            "h2": {"yes": 0.2, "no": 0.8},
        }
        eig = aqp.expected_info_gain(priors, model)
        self.assertGreater(eig, 0.0)
        self.assertLess(eig, 1.0)

    def test_scalar_prediction_coerced(self) -> None:
        # Deterministic predictions — each hypothesis maps to one value
        priors = {"h1": 0.5, "h2": 0.5}
        model = {"h1": "yes", "h2": "no"}
        self.assertAlmostEqual(
            aqp.expected_info_gain(priors, model), 1.0,
        )

    def test_missing_hypothesis_in_model_handled(self) -> None:
        # h2 absent from model — likelihood treated as 0 for all answers
        priors = {"h1": 0.5, "h2": 0.5}
        model = {"h1": {"yes": 1.0}}
        # Not an error, just low gain
        eig = aqp.expected_info_gain(priors, model)
        self.assertGreaterEqual(eig, 0.0)

    def test_empty_hypotheses_zero(self) -> None:
        self.assertEqual(aqp.expected_info_gain({}, {}), 0.0)


class TestRank(unittest.TestCase):
    def test_better_query_ranked_first(self) -> None:
        priors = {"h1": 0.5, "h2": 0.5}
        queries = {
            "useless": {
                "h1": {"yes": 0.5, "no": 0.5},
                "h2": {"yes": 0.5, "no": 0.5},
            },
            "perfect": {
                "h1": {"yes": 1.0, "no": 0.0},
                "h2": {"yes": 0.0, "no": 1.0},
            },
            "weak": {
                "h1": {"yes": 0.6, "no": 0.4},
                "h2": {"yes": 0.4, "no": 0.6},
            },
        }
        ranked = aqp.rank(priors, queries)
        self.assertEqual(ranked[0].query_id, "perfect")
        self.assertEqual(ranked[-1].query_id, "useless")


class TestRankWithCost(unittest.TestCase):
    def test_cost_trades_off_gain(self) -> None:
        priors = {"h1": 0.5, "h2": 0.5}
        queries = {
            "expensive_perfect": {
                "h1": "yes", "h2": "no",   # EIG = 1 bit
            },
            "cheap_weak": {
                "h1": {"yes": 0.7, "no": 0.3},
                "h2": {"yes": 0.3, "no": 0.7},
            },
        }
        costs = {"expensive_perfect": 100.0, "cheap_weak": 1.0}
        ranked = aqp.rank_with_cost(priors, queries, costs)
        # Cheap weak beats expensive perfect on EIG/cost
        self.assertEqual(ranked[0].query_id, "cheap_weak")

    def test_unknown_cost_defaults_one(self) -> None:
        priors = {"h1": 0.5, "h2": 0.5}
        queries = {"q": {"h1": "a", "h2": "b"}}
        ranked = aqp.rank_with_cost(priors, queries, costs=None)
        self.assertEqual(ranked[0].cost, 1.0)


class TestBest(unittest.TestCase):
    def test_best_picks_top_ranked(self) -> None:
        priors = {"h1": 0.5, "h2": 0.5}
        queries = {
            "a": {"h1": "yes", "h2": "yes"},      # useless
            "b": {"h1": "yes", "h2": "no"},       # perfect
        }
        best = aqp.best(priors, queries)
        self.assertEqual(best.query_id, "b")

    def test_no_queries_returns_none(self) -> None:
        self.assertIsNone(aqp.best({"h1": 1.0}, {}))


class TestDict(unittest.TestCase):
    def test_query_value_serialises(self) -> None:
        qv = aqp.QueryValue(
            query_id="q", expected_info_gain=0.5,
            expected_info_gain_per_cost=0.25, cost=2.0,
        )
        d = qv.as_dict()
        self.assertEqual(d["query_id"], "q")
        self.assertEqual(d["cost"], 2.0)


if __name__ == "__main__":
    unittest.main()
