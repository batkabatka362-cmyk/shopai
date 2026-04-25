"""Information gain tests — EIG, ranking, budget picker."""
from __future__ import annotations

import unittest

from core.brain import information_gain as ig


class TestEntropy(unittest.TestCase):
    def test_uniform_prior_has_high_entropy(self) -> None:
        # Beta(1,1) = uniform has max differential entropy for [0,1]
        h_uniform = ig._beta_entropy(1.0, 1.0)
        h_peaked = ig._beta_entropy(20.0, 20.0)
        self.assertGreater(h_uniform, h_peaked)

    def test_zero_or_negative_returns_zero(self) -> None:
        self.assertEqual(ig._beta_entropy(0, 1), 0.0)
        self.assertEqual(ig._beta_entropy(-1, 1), 0.0)


class TestEIG(unittest.TestCase):
    def test_more_observations_means_more_gain(self) -> None:
        small = ig.expected_information_gain(1, 1, 2)
        large = ig.expected_information_gain(1, 1, 50)
        self.assertGreater(large, small)

    def test_peaked_prior_less_gain_than_uniform(self) -> None:
        g_peaked = ig.expected_information_gain(50, 50, 10)
        g_uniform = ig.expected_information_gain(1, 1, 10)
        self.assertGreater(g_uniform, g_peaked)

    def test_zero_obs_zero_gain(self) -> None:
        self.assertEqual(ig.expected_information_gain(1, 1, 0), 0.0)


class TestRank(unittest.TestCase):
    def test_ranks_by_utility(self) -> None:
        cands = [
            ig.Candidate(id="cheap_novel", label="c1",
                          prior_alpha=1, prior_beta=1,
                          cost_usd=5, expected_observations=20,
                          epistemic_novelty=0.9),
            ig.Candidate(id="expensive_known", label="c2",
                          prior_alpha=40, prior_beta=40,
                          cost_usd=80, expected_observations=5,
                          epistemic_novelty=0.1),
        ]
        r = ig.rank(cands)
        self.assertEqual(r.best.candidate.id, "cheap_novel")

    def test_empty_candidates_empty_ranking(self) -> None:
        r = ig.rank([])
        self.assertIsNone(r.best)
        self.assertEqual(len(r.top), 0)

    def test_top_k_honoured(self) -> None:
        cands = [
            ig.Candidate(id=f"c{i}", label=f"c{i}",
                          expected_observations=5 + i)
            for i in range(20)
        ]
        r = ig.rank(cands, top_k=3)
        self.assertEqual(len(r.top), 3)

    def test_rationale_mentions_eig(self) -> None:
        r = ig.rank([ig.Candidate(id="x", label="x",
                                    expected_observations=30)])
        self.assertIn("EIG", r.best.rationale)


class TestPickUnderBudget(unittest.TestCase):
    def test_picks_greedy_until_budget_empty(self) -> None:
        cands = [
            ig.Candidate(id="A", label="a", cost_usd=20,
                          expected_observations=30),
            ig.Candidate(id="B", label="b", cost_usd=30,
                          expected_observations=20),
            ig.Candidate(id="C", label="c", cost_usd=50,
                          expected_observations=10),
        ]
        picked = ig.pick_under_budget(cands, total_budget_usd=55)
        picked_ids = {p.candidate.id for p in picked}
        # A + B = 50 fits; C alone is 50 but greedy picked A first
        # then would skip B if cheaper alternatives ranked lower.
        self.assertIn("A", picked_ids)

    def test_zero_budget_picks_nothing(self) -> None:
        cands = [ig.Candidate(id="x", label="x", cost_usd=10)]
        picked = ig.pick_under_budget(cands, total_budget_usd=0)
        self.assertEqual(picked, [])


class TestCandidate(unittest.TestCase):
    def test_prior_mean_and_variance(self) -> None:
        c = ig.Candidate(id="x", label="x",
                          prior_alpha=3, prior_beta=1)
        self.assertAlmostEqual(c.prior_mean, 0.75)
        # Beta(3,1) var = 3*1/(4^2 * 5) = 3/80
        self.assertAlmostEqual(c.prior_variance, 3/80, places=4)


if __name__ == "__main__":
    unittest.main()
