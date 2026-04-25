"""Belief propagator tests."""
from __future__ import annotations

import unittest

from core.memory import belief_propagator as bp


class TestConfig(unittest.TestCase):
    def test_invalid_thresholds_raise(self) -> None:
        with self.assertRaises(ValueError):
            bp.BeliefPropagator(
                confident_threshold=0.5,
                ambiguous_threshold=0.6,
            )


class TestMergeUnanimous(unittest.TestCase):
    def setUp(self) -> None:
        self.p = bp.BeliefPropagator()

    def test_unanimous_claim_is_confident(self) -> None:
        claims = [
            bp.Claim("p1", "price", 29.99, "shopify", 0.9),
            bp.Claim("p1", "price", 29.99, "autods", 0.8),
        ]
        b = self.p.merge(claims)
        self.assertEqual(b.value, 29.99)
        self.assertEqual(b.verdict, "confident")
        self.assertAlmostEqual(b.probability, 1.0)


class TestMergeConflict(unittest.TestCase):
    def setUp(self) -> None:
        self.p = bp.BeliefPropagator()

    def test_two_way_conflict_ambiguous(self) -> None:
        claims = [
            bp.Claim("p1", "price", 29.99, "a", 0.9),
            bp.Claim("p1", "price", 30.49, "b", 0.85),
        ]
        b = self.p.merge(claims)
        # One side wins narrowly → not confident, but more than half
        self.assertNotEqual(b.verdict, "confident")
        self.assertLess(b.probability, 0.75)

    def test_split_three_ways_conflicted(self) -> None:
        claims = [
            bp.Claim("p1", "color", "red", "a", 0.5),
            bp.Claim("p1", "color", "blue", "b", 0.5),
            bp.Claim("p1", "color", "green", "c", 0.5),
        ]
        b = self.p.merge(claims)
        # Three-way split → highest probability ≈ 0.33 → conflicted
        self.assertEqual(b.verdict, "conflicted")
        self.assertLess(b.probability, 0.5)


class TestTrustLookup(unittest.TestCase):
    def test_trusted_source_wins(self) -> None:
        p = bp.BeliefPropagator()
        claims = [
            bp.Claim("p1", "x", "A", "trusted", 0.8),
            bp.Claim("p1", "x", "B", "noisy", 0.8),
        ]
        trust = {"trusted": 0.95, "noisy": 0.2}
        b = p.merge(claims, trust_fn=lambda s: trust.get(s, 0.5))
        self.assertEqual(b.value, "A")

    def test_trust_fn_exception_handled(self) -> None:
        def bad(_s):
            raise RuntimeError("x")

        p = bp.BeliefPropagator()
        claims = [
            bp.Claim("p1", "x", "A", "src", 0.9),
        ]
        # Should fall back to trust=1.0 without raising
        b = p.merge(claims, trust_fn=bad)
        self.assertEqual(b.value, "A")


class TestFloatBucketing(unittest.TestCase):
    def test_tiny_float_drift_same_bucket(self) -> None:
        p = bp.BeliefPropagator()
        claims = [
            bp.Claim("p1", "ratio", 0.123456789, "a", 0.8),
            bp.Claim("p1", "ratio", 0.123456790, "b", 0.8),
        ]
        b = p.merge(claims)
        # Same bucket → confident
        self.assertEqual(b.verdict, "confident")


class TestEdgeCases(unittest.TestCase):
    def test_empty_returns_none(self) -> None:
        p = bp.BeliefPropagator()
        self.assertIsNone(p.merge([]))

    def test_mixed_subject_raises(self) -> None:
        p = bp.BeliefPropagator()
        with self.assertRaises(ValueError):
            p.merge([
                bp.Claim("a", "x", 1, "s"),
                bp.Claim("b", "x", 1, "t"),
            ])

    def test_dict_claims_coerced(self) -> None:
        p = bp.BeliefPropagator()
        b = p.merge([
            {"subject": "p1", "predicate": "name",
             "value": "Blue", "source": "shopify",
             "confidence": 0.9},
            {"subject": "p1", "predicate": "name",
             "value": "Blue", "source": "autods",
             "confidence": 0.8},
        ])
        self.assertEqual(b.value, "Blue")

    def test_malformed_dict_skipped(self) -> None:
        p = bp.BeliefPropagator()
        b = p.merge([
            {"subject": "p1", "predicate": "name",
             "value": "A", "confidence": 0.9, "source": "s"},
            {"no_required_fields": True},
        ])
        self.assertIsNotNone(b)
        self.assertEqual(b.value, "A")

    def test_all_zero_weight_returns_unknown(self) -> None:
        p = bp.BeliefPropagator()
        b = p.merge([
            bp.Claim("p1", "x", "A", "s", 0.0),
        ])
        self.assertEqual(b.verdict, "unknown")


class TestBatch(unittest.TestCase):
    def test_merge_batch_groups_by_sp(self) -> None:
        p = bp.BeliefPropagator()
        out = p.merge_batch([
            bp.Claim("p1", "price", 10, "a"),
            bp.Claim("p1", "price", 10, "b"),
            bp.Claim("p1", "color", "red", "a"),
            bp.Claim("p2", "price", 20, "c"),
        ])
        keys = {(b.subject, b.predicate) for b in out}
        self.assertEqual(
            keys,
            {("p1", "price"), ("p1", "color"), ("p2", "price")},
        )


class TestSupport(unittest.TestCase):
    def test_support_lists_all_candidates(self) -> None:
        p = bp.BeliefPropagator()
        b = p.merge([
            bp.Claim("p1", "x", "A", "s1", 0.5),
            bp.Claim("p1", "x", "A", "s2", 0.5),
            bp.Claim("p1", "x", "B", "s3", 0.4),
        ])
        values = {s["value"] for s in b.support}
        self.assertEqual(values, {"A", "B"})
        a_support = next(s for s in b.support if s["value"] == "A")
        self.assertEqual(a_support["n"], 2)
        self.assertIn("s1", a_support["sources"])


class TestDict(unittest.TestCase):
    def test_belief_and_claim_serialise(self) -> None:
        p = bp.BeliefPropagator()
        b = p.merge([
            bp.Claim("p1", "name", "A", "s", 0.8),
        ])
        d = b.as_dict()
        self.assertIn("support", d)
        self.assertIn("verdict", d)
        cd = bp.Claim("a", "b", "c", "s", 0.5).as_dict()
        self.assertEqual(cd["source"], "s")


if __name__ == "__main__":
    unittest.main()
