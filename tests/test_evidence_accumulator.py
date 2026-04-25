"""Evidence accumulator tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import evidence_accumulator as ea


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.a = ea.EvidenceAccumulator()

    def test_blank_statement_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.a.register_claim("")

    def test_bad_prior_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.a.register_claim("x", prior_alpha=0)

    def test_uniform_prior_is_half(self) -> None:
        c = self.a.register_claim("product p1 is winner")
        self.assertAlmostEqual(c.probability, 0.5, places=3)

    def test_idempotent(self) -> None:
        c1 = self.a.register_claim(
            "x", claim_id="c1",
        )
        c2 = self.a.register_claim(
            "x", claim_id="c1",
        )
        self.assertEqual(c1.claim_id, c2.claim_id)


class TestAddEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self.a = ea.EvidenceAccumulator()
        self.c = self.a.register_claim("winner", claim_id="c")

    def test_unknown_claim_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.a.add_evidence(
                claim_id="nope", polarity="support",
            )

    def test_bad_polarity_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.a.add_evidence(
                claim_id="c",
                polarity="maybe",  # type: ignore[arg-type]
            )

    def test_bad_weight_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.a.add_evidence(
                claim_id="c",
                polarity="support", weight=2.0,
            )

    def test_support_raises_probability(self) -> None:
        for _ in range(5):
            self.a.add_evidence(
                claim_id="c",
                polarity="support", weight=1.0,
            )
        p = self.a.probability("c")
        # alpha=6, beta=1 → 6/7 ≈ 0.857
        self.assertGreater(p, 0.7)

    def test_contradict_lowers(self) -> None:
        for _ in range(5):
            self.a.add_evidence(
                claim_id="c",
                polarity="contradict", weight=1.0,
            )
        self.assertLess(self.a.probability("c"), 0.3)


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.a = ea.EvidenceAccumulator()
        self.a.register_claim("c", claim_id="c")

    def test_probability_unknown_zero(self) -> None:
        self.assertEqual(self.a.probability("nope"), 0.0)

    def test_evidence_gap_shrinks(self) -> None:
        gap0 = self.a.evidence_gap("c")
        for _ in range(20):
            self.a.add_evidence(
                claim_id="c",
                polarity="support", weight=1.0,
            )
        gap1 = self.a.evidence_gap("c")
        self.assertLess(gap1, gap0)

    def test_credible_interval_unknown(self) -> None:
        lo, hi = self.a.credible_interval("nope")
        self.assertEqual(lo, 0.0)
        self.assertEqual(hi, 1.0)

    def test_credible_interval_narrows(self) -> None:
        for _ in range(30):
            self.a.add_evidence(
                claim_id="c",
                polarity="support", weight=1.0,
            )
        lo, hi = self.a.credible_interval("c")
        self.assertLess(hi - lo, 0.3)

    def test_strongest(self) -> None:
        self.a.add_evidence(
            claim_id="c", polarity="support",
            weight=0.2, source="weak",
        )
        self.a.add_evidence(
            claim_id="c", polarity="support",
            weight=0.9, source="strong",
        )
        top = self.a.strongest("c", polarity="support")
        self.assertEqual(top[0].source, "strong")

    def test_claims_sorted(self) -> None:
        self.a.register_claim("low", claim_id="low")
        self.a.register_claim("high", claim_id="high")
        self.a.add_evidence(
            claim_id="high", polarity="support",
        )
        claims = self.a.claims()
        # high should have higher probability
        self.assertEqual(claims[0].claim_id, "high")


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "e.db"
        first = ea.EvidenceAccumulator(path)
        first.register_claim("x", claim_id="c")
        first.add_evidence(
            claim_id="c", polarity="support", weight=0.8,
        )
        first.close()
        second = ea.EvidenceAccumulator(path)
        p = second.probability("c")
        self.assertGreater(p, 0.5)
        self.assertEqual(second.stats()["total_evidence"], 1)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        a = ea.EvidenceAccumulator()
        a.register_claim("x", claim_id="c")
        a.add_evidence(
            claim_id="c", polarity="support",
        )
        s = a.stats()
        self.assertEqual(s["claims"], 1)
        self.assertEqual(s["total_evidence"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        a = ea.EvidenceAccumulator()
        a.register_claim("x", claim_id="c")
        self.assertEqual(a.reset(), 1)


class TestDict(unittest.TestCase):
    def test_item_serialises(self) -> None:
        a = ea.EvidenceAccumulator()
        a.register_claim("x", claim_id="c")
        item = a.add_evidence(
            claim_id="c", polarity="support",
        )
        self.assertEqual(item.as_dict()["polarity"], "support")

    def test_posterior_serialises(self) -> None:
        a = ea.EvidenceAccumulator()
        a.register_claim("x", claim_id="c")
        c = a.posterior("c")
        d = c.as_dict()
        self.assertIn("probability", d)


if __name__ == "__main__":
    unittest.main()
