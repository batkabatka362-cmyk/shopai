"""Bayes network tests — schema, CPT, inference."""
from __future__ import annotations

import unittest

from core.brain import bayesnet as bn


class TestSchema(unittest.TestCase):
    def test_add_with_prior(self) -> None:
        net = bn.BayesNet()
        net.add("niche", ["audio", "fashion"],
                 prior={"audio": 0.6, "fashion": 0.4})
        self.assertIn("niche", net.nodes())

    def test_add_without_prior_is_uniform(self) -> None:
        net = bn.BayesNet()
        net.add("x", ["a", "b"])
        p = net.query(target="x", target_value="a")
        self.assertAlmostEqual(p, 0.5)

    def test_parents_require_cpt(self) -> None:
        net = bn.BayesNet()
        net.add("niche", ["audio"], prior={"audio": 1.0})
        with self.assertRaises(ValueError):
            net.add("sale", ["yes", "no"], parents=["niche"])

    def test_missing_cpt_row_raises(self) -> None:
        net = bn.BayesNet()
        net.add("niche", ["audio", "fashion"],
                 prior={"audio": 0.5, "fashion": 0.5})
        with self.assertRaises(ValueError):
            net.add("sale", ["yes", "no"], parents=["niche"],
                     cpt={("audio",): {"yes": 0.5, "no": 0.5}})

    def test_missing_value_in_row_raises(self) -> None:
        net = bn.BayesNet()
        net.add("niche", ["audio", "fashion"],
                 prior={"audio": 0.5, "fashion": 0.5})
        with self.assertRaises(ValueError):
            net.add(
                "sale", ["yes", "no"], parents=["niche"],
                cpt={("audio",): {"yes": 0.5},
                     ("fashion",): {"yes": 0.5, "no": 0.5}},
            )


class TestInference(unittest.TestCase):
    def _sale_net(self) -> bn.BayesNet:
        net = bn.BayesNet()
        net.add("niche", ["audio", "fashion"],
                 prior={"audio": 0.6, "fashion": 0.4})
        net.add(
            "sale", ["yes", "no"], parents=["niche"],
            cpt={
                ("audio",): {"yes": 0.8, "no": 0.2},
                ("fashion",): {"yes": 0.2, "no": 0.8},
            },
        )
        return net

    def test_marginal_query(self) -> None:
        net = self._sale_net()
        # P(sale=yes) = 0.6*0.8 + 0.4*0.2 = 0.56
        p = net.query(target="sale", target_value="yes")
        self.assertAlmostEqual(p, 0.56, places=3)

    def test_conditional_query(self) -> None:
        net = self._sale_net()
        p = net.query(target="sale", target_value="yes",
                        evidence={"niche": "audio"})
        self.assertAlmostEqual(p, 0.8, places=3)

    def test_full_distribution(self) -> None:
        net = self._sale_net()
        dist = net.query(target="sale")
        self.assertAlmostEqual(dist["yes"], 0.56, places=3)
        self.assertAlmostEqual(dist["no"], 0.44, places=3)


class TestMultiParent(unittest.TestCase):
    def test_two_parents(self) -> None:
        net = bn.BayesNet()
        net.add("niche", ["audio", "fashion"],
                 prior={"audio": 0.5, "fashion": 0.5})
        net.add("tone", ["luxury", "friendly"],
                 prior={"luxury": 0.5, "friendly": 0.5})
        net.add(
            "sale", ["yes", "no"], parents=["niche", "tone"],
            cpt={
                ("audio", "luxury"): {"yes": 0.9, "no": 0.1},
                ("audio", "friendly"): {"yes": 0.6, "no": 0.4},
                ("fashion", "luxury"): {"yes": 0.5, "no": 0.5},
                ("fashion", "friendly"): {"yes": 0.2, "no": 0.8},
            },
        )
        p = net.query(target="sale", target_value="yes",
                        evidence={"niche": "audio", "tone": "luxury"})
        self.assertAlmostEqual(p, 0.9, places=3)


class TestErrors(unittest.TestCase):
    def test_unknown_target_raises(self) -> None:
        net = bn.BayesNet()
        net.add("x", ["a"])
        with self.assertRaises(KeyError):
            net.query(target="nope", target_value="a")

    def test_unknown_evidence_raises(self) -> None:
        net = bn.BayesNet()
        net.add("x", ["a"])
        with self.assertRaises(KeyError):
            net.query(target="x", target_value="a",
                        evidence={"nope": "a"})

    def test_unknown_target_value_raises(self) -> None:
        net = bn.BayesNet()
        net.add("x", ["a", "b"])
        with self.assertRaises(KeyError):
            net.query(target="x", target_value="missing")


class TestNormalisation(unittest.TestCase):
    def test_unnormalised_prior_gets_normalised(self) -> None:
        net = bn.BayesNet()
        net.add("x", ["a", "b"], prior={"a": 3, "b": 1})
        p_a = net.query(target="x", target_value="a")
        self.assertAlmostEqual(p_a, 0.75)


class TestDescribe(unittest.TestCase):
    def test_describe_returns_metadata(self) -> None:
        net = bn.BayesNet()
        net.add("niche", ["audio", "fashion"],
                 prior={"audio": 0.5, "fashion": 0.5})
        net.add(
            "sale", ["yes", "no"], parents=["niche"],
            cpt={("audio",): {"yes": 0.8, "no": 0.2},
                 ("fashion",): {"yes": 0.2, "no": 0.8}},
        )
        d = net.describe("sale")
        self.assertEqual(d["parents"], ["niche"])
        self.assertEqual(d["cpt_rows"], 2)


if __name__ == "__main__":
    unittest.main()
