"""Causal discovery tests."""
from __future__ import annotations

import random
import unittest

from core.brain import causal_discovery as cd


class TestCorrelation(unittest.TestCase):
    def test_perfect_correlation(self) -> None:
        xs = [1, 2, 3, 4]
        ys = [2, 4, 6, 8]
        self.assertAlmostEqual(cd.correlation(xs, ys), 1.0, places=3)

    def test_negative_correlation(self) -> None:
        xs = [1, 2, 3, 4]
        ys = [4, 3, 2, 1]
        self.assertAlmostEqual(cd.correlation(xs, ys), -1.0, places=3)

    def test_empty_returns_zero(self) -> None:
        self.assertEqual(cd.correlation([], []), 0.0)

    def test_unequal_length_returns_zero(self) -> None:
        self.assertEqual(cd.correlation([1, 2], [1]), 0.0)


class TestPartialCorrelation(unittest.TestCase):
    def test_empty_conditioning_equals_correlation(self) -> None:
        xs = [1, 2, 3, 4]
        ys = [1, 2, 3, 4]
        r = cd.partial_correlation(xs, ys, [])
        self.assertAlmostEqual(r, 1.0, places=3)

    def test_confounder_breaks_apparent_link(self) -> None:
        # X = Z + noise, Y = Z + noise → r(X,Y) > 0, but r(X,Y|Z) ≈ 0.
        rng = random.Random(7)
        zs = list(range(50))
        xs = [z + rng.uniform(-0.1, 0.1) for z in zs]
        ys = [z + rng.uniform(-0.1, 0.1) for z in zs]
        r_marginal = cd.correlation(xs, ys)
        r_partial = cd.partial_correlation(xs, ys, [zs])
        self.assertGreater(r_marginal, 0.9)
        self.assertLess(abs(r_partial), 0.5)


class TestDiscover(unittest.TestCase):
    def test_independent_no_edges(self) -> None:
        rng = random.Random(0)
        samples = [
            {"a": rng.random(), "b": rng.random()}
            for _ in range(100)
        ]
        g = cd.discover(samples)
        self.assertEqual(g.edges, [])

    def test_correlated_pair_becomes_edge(self) -> None:
        samples = [
            {"a": i / 10.0, "b": i / 10.0 + 0.01}
            for i in range(50)
        ]
        g = cd.discover(samples)
        self.assertEqual(len(g.edges), 1)
        edge = g.edges[0]
        self.assertSetEqual({edge.source, edge.target}, {"a", "b"})

    def test_confounded_indirect_pair_pruned(self) -> None:
        # A ← Z → B : a/b correlated marginally but conditionally
        # independent given z, so discover should NOT emit an edge
        # between a and b.
        rng = random.Random(1)
        samples = []
        for _ in range(100):
            z = rng.random()
            samples.append({
                "z": z,
                "a": z + rng.uniform(-0.05, 0.05),
                "b": z + rng.uniform(-0.05, 0.05),
            })
        g = cd.discover(samples)
        ab_edges = [
            e for e in g.edges
            if {e.source, e.target} == {"a", "b"}
        ]
        self.assertEqual(ab_edges, [])
        # But z-a and z-b should survive
        other_edges = [
            {e.source, e.target} for e in g.edges
        ]
        self.assertIn({"z", "a"}, other_edges)
        self.assertIn({"z", "b"}, other_edges)

    def test_temporal_ordering_directs_edges(self) -> None:
        samples = [
            {"cause": i / 10.0, "effect": i / 10.0 + 0.01}
            for i in range(50)
        ]
        g = cd.discover(
            samples,
            temporal_order={"cause": 1, "effect": 2},
        )
        self.assertTrue(g.edges[0].directed)
        self.assertEqual(g.edges[0].source, "cause")
        self.assertEqual(g.edges[0].target, "effect")

    def test_empty_samples_empty_graph(self) -> None:
        g = cd.discover([])
        self.assertEqual(g.variables, [])

    def test_single_variable_no_edges(self) -> None:
        samples = [{"x": i} for i in range(5)]
        g = cd.discover(samples)
        self.assertEqual(g.edges, [])


class TestParents(unittest.TestCase):
    def test_parents_of_directed_edge(self) -> None:
        g = cd.CausalGraph(
            variables=["a", "b"],
            edges=[cd.Edge(source="a", target="b",
                             directed=True, strength=0.9)],
        )
        self.assertEqual(g.parents_of("b"), ["a"])
        self.assertEqual(g.parents_of("a"), [])


class TestDescribe(unittest.TestCase):
    def test_describe_empty(self) -> None:
        g = cd.CausalGraph(variables=["a", "b"])
        text = cd.describe(g)
        self.assertIn("No causal edges", text)

    def test_describe_with_edges(self) -> None:
        g = cd.CausalGraph(
            variables=["a", "b"],
            edges=[cd.Edge(source="a", target="b",
                             directed=True, strength=0.9)],
        )
        text = cd.describe(g)
        self.assertIn("a", text)
        self.assertIn("b", text)
        self.assertIn("→", text)


if __name__ == "__main__":
    unittest.main()
