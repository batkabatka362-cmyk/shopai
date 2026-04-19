"""Principle extractor tests."""
from __future__ import annotations

import unittest

from core.brain import principle_extractor as pe


class TestConfig(unittest.TestCase):
    def test_bad_min_raises(self) -> None:
        with self.assertRaises(ValueError):
            pe.PrincipleExtractor(min_rules=1)

    def test_bad_threshold_raises(self) -> None:
        with self.assertRaises(ValueError):
            pe.PrincipleExtractor(similarity_threshold=0)


class TestExtract(unittest.TestCase):
    def setUp(self) -> None:
        self.ex = pe.PrincipleExtractor(
            min_rules=2, similarity_threshold=0.3,
        )

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(self.ex.extract([]), [])

    def test_single_rule_skipped(self) -> None:
        rules = [pe.Rule(
            id="r1", antecedent="roas < 1.5",
            consequent="kill",
        )]
        self.assertEqual(self.ex.extract(rules), [])

    def test_two_similar_rules_one_principle(self) -> None:
        rules = [
            pe.Rule(
                id="r1",
                antecedent="roas < 1.5 and days >= 3",
                consequent="kill",
            ),
            pe.Rule(
                id="r2",
                antecedent="roas < 1.3 and days >= 3",
                consequent="kill",
            ),
        ]
        principles = self.ex.extract(rules)
        self.assertEqual(len(principles), 1)
        p = principles[0]
        self.assertEqual(p.consequent, "kill")
        self.assertIn("roas", p.threshold_ranges)
        self.assertEqual(
            p.threshold_ranges["roas"], (1.3, 1.5),
        )

    def test_different_consequents_separate(self) -> None:
        rules = [
            pe.Rule(
                id="r1", antecedent="roas < 1.5",
                consequent="kill",
            ),
            pe.Rule(
                id="r2", antecedent="roas < 1.3",
                consequent="kill",
            ),
            pe.Rule(
                id="r3", antecedent="cvr < 0.5",
                consequent="pause",
            ),
            pe.Rule(
                id="r4", antecedent="cvr < 0.4",
                consequent="pause",
            ),
        ]
        principles = self.ex.extract(rules)
        self.assertEqual(len(principles), 2)
        consequents = {p.consequent for p in principles}
        self.assertEqual(consequents, {"kill", "pause"})

    def test_shared_terms_found(self) -> None:
        rules = [
            pe.Rule(
                id="r1",
                antecedent="roas < 1.5 and days >= 3",
                consequent="kill",
            ),
            pe.Rule(
                id="r2",
                antecedent="roas < 1.3 and days >= 3",
                consequent="kill",
            ),
            pe.Rule(
                id="r3",
                antecedent="roas < 1.7 and days >= 3",
                consequent="kill",
            ),
        ]
        principles = self.ex.extract(rules)
        p = principles[0]
        self.assertIn("roas", p.shared_terms)
        self.assertIn("days", p.shared_terms)

    def test_threshold_range_expansion(self) -> None:
        rules = [
            pe.Rule(id=f"r{i}", antecedent=f"roas < {1.3 + i * 0.1}", consequent="kill")
            for i in range(3)
        ]
        principles = self.ex.extract(rules)
        p = principles[0]
        lo, hi = p.threshold_ranges["roas"]
        self.assertAlmostEqual(lo, 1.3)
        self.assertAlmostEqual(hi, 1.5)

    def test_support_aggregated(self) -> None:
        rules = [
            pe.Rule(
                id="r1", antecedent="roas < 1.5",
                consequent="kill", support=10, confidence=0.8,
            ),
            pe.Rule(
                id="r2", antecedent="roas < 1.3",
                consequent="kill", support=5, confidence=0.6,
            ),
        ]
        principles = self.ex.extract(rules)
        self.assertEqual(principles[0].support_total, 15)
        self.assertAlmostEqual(
            principles[0].avg_confidence, 0.7,
        )

    def test_dissimilar_rules_not_merged(self) -> None:
        ex = pe.PrincipleExtractor(
            min_rules=2, similarity_threshold=0.8,
        )
        rules = [
            pe.Rule(
                id="r1",
                antecedent="roas < 1.5",
                consequent="kill",
            ),
            pe.Rule(
                id="r2",
                antecedent="cpm > 25 with niche pet",
                consequent="kill",
            ),
        ]
        # Very different antecedents → no principle
        self.assertEqual(ex.extract(rules), [])


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        ex = pe.PrincipleExtractor()
        s = ex.stats()
        self.assertIn("min_rules", s)
        self.assertIn("similarity_threshold", s)


class TestDict(unittest.TestCase):
    def test_rule_serialises(self) -> None:
        r = pe.Rule(
            id="r", antecedent="x < 1", consequent="y",
        )
        d = r.as_dict()
        self.assertEqual(d["id"], "r")

    def test_principle_serialises(self) -> None:
        ex = pe.PrincipleExtractor()
        rules = [
            pe.Rule(
                id="r1", antecedent="roas < 1.5 and days >= 3",
                consequent="kill",
            ),
            pe.Rule(
                id="r2", antecedent="roas < 1.3 and days >= 3",
                consequent="kill",
            ),
        ]
        principles = ex.extract(rules)
        d = principles[0].as_dict()
        self.assertIn("summary", d)
        self.assertIn("threshold_ranges", d)


if __name__ == "__main__":
    unittest.main()
