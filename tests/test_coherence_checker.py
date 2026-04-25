"""Coherence checker tests."""
from __future__ import annotations

import unittest

from core.brain import coherence_checker as cc


class TestBelief(unittest.TestCase):
    def test_bad_polarity_raises(self) -> None:
        with self.assertRaises(ValueError):
            cc.Belief(
                id="x", predicate="p", subject="s",
                polarity="maybe",  # type: ignore[arg-type]
                evidence_score=0.5,
            )

    def test_bad_evidence_raises(self) -> None:
        with self.assertRaises(ValueError):
            cc.Belief(
                id="x", predicate="p", subject="s",
                polarity="asserts", evidence_score=2.0,
            )


class TestAssert(unittest.TestCase):
    def setUp(self) -> None:
        self.c = cc.CoherenceChecker()

    def test_blank_predicate_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.c.assert_belief(
                predicate="", subject="s",
            )

    def test_blank_subject_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.c.assert_belief(
                predicate="p", subject="",
            )

    def test_asserts_stored(self) -> None:
        b = self.c.assert_belief(
            predicate="is_winner",
            subject="product_p1",
            evidence_score=0.8,
        )
        self.assertEqual(b.polarity, "asserts")

    def test_stronger_evidence_overwrites(self) -> None:
        b1 = self.c.assert_belief(
            predicate="p", subject="s",
            evidence_score=0.5,
        )
        b2 = self.c.assert_belief(
            predicate="p", subject="s",
            evidence_score=0.9,
        )
        # b1 should have been replaced
        self.assertNotEqual(b1.id, b2.id)
        self.assertEqual(len(self.c.beliefs()), 1)

    def test_weaker_evidence_kept(self) -> None:
        b1 = self.c.assert_belief(
            predicate="p", subject="s",
            evidence_score=0.9,
        )
        b2 = self.c.assert_belief(
            predicate="p", subject="s",
            evidence_score=0.1,
        )
        # Should return original
        self.assertEqual(b1.id, b2.id)


class TestRetract(unittest.TestCase):
    def test_retract(self) -> None:
        c = cc.CoherenceChecker()
        b = c.assert_belief(predicate="p", subject="s")
        self.assertTrue(c.retract(b.id))
        self.assertEqual(len(c.beliefs()), 0)

    def test_retract_unknown(self) -> None:
        c = cc.CoherenceChecker()
        self.assertFalse(c.retract("nope"))


class TestCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.c = cc.CoherenceChecker()
        self.c.assert_belief(
            predicate="is_winner",
            subject="product_p1",
            polarity="asserts",
            evidence_score=0.9,
        )

    def test_matching_claim_no_contradiction(self) -> None:
        claims = [cc.Claim(
            predicate="is_winner",
            subject="product_p1",
            polarity="asserts", confidence=0.8,
        )]
        self.assertEqual(self.c.check(claims), [])

    def test_opposite_polarity_contradicts(self) -> None:
        claims = [cc.Claim(
            predicate="is_winner",
            subject="product_p1",
            polarity="denies", confidence=0.7,
        )]
        found = self.c.check(claims)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0].severity, 0.7)

    def test_different_subject_no_contradiction(self) -> None:
        claims = [cc.Claim(
            predicate="is_winner",
            subject="product_p2",
            polarity="denies", confidence=0.7,
        )]
        self.assertEqual(self.c.check(claims), [])

    def test_severity_is_min(self) -> None:
        # Belief evidence 0.9, claim confidence 0.3 → severity 0.3
        claims = [cc.Claim(
            predicate="is_winner",
            subject="product_p1",
            polarity="denies", confidence=0.3,
        )]
        found = self.c.check(claims)
        self.assertAlmostEqual(found[0].severity, 0.3)


class TestIsCoherent(unittest.TestCase):
    def test_coherent_below_floor(self) -> None:
        c = cc.CoherenceChecker()
        c.assert_belief(
            predicate="p", subject="s",
            polarity="asserts", evidence_score=0.2,
        )
        claims = [cc.Claim(
            predicate="p", subject="s",
            polarity="denies", confidence=0.2,
        )]
        # severity = 0.2 < 0.3 floor → coherent
        self.assertTrue(c.is_coherent(claims))

    def test_not_coherent_above_floor(self) -> None:
        c = cc.CoherenceChecker()
        c.assert_belief(
            predicate="p", subject="s",
            polarity="asserts", evidence_score=0.8,
        )
        claims = [cc.Claim(
            predicate="p", subject="s",
            polarity="denies", confidence=0.8,
        )]
        self.assertFalse(c.is_coherent(claims))


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        c = cc.CoherenceChecker()
        c.assert_belief(predicate="a", subject="s")
        c.assert_belief(
            predicate="b", subject="s", polarity="denies",
        )
        s = c.stats()
        self.assertEqual(s["beliefs"], 2)
        self.assertEqual(s["by_polarity"]["asserts"], 1)
        self.assertEqual(s["by_polarity"]["denies"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        c = cc.CoherenceChecker()
        c.assert_belief(predicate="p", subject="s")
        self.assertEqual(c.reset(), 1)


class TestDict(unittest.TestCase):
    def test_belief_serialises(self) -> None:
        c = cc.CoherenceChecker()
        b = c.assert_belief(predicate="p", subject="s")
        d = b.as_dict()
        self.assertEqual(d["predicate"], "p")

    def test_contradiction_serialises(self) -> None:
        c = cc.CoherenceChecker()
        c.assert_belief(
            predicate="p", subject="s",
            evidence_score=0.8,
        )
        claims = [cc.Claim(
            predicate="p", subject="s",
            polarity="denies", confidence=0.8,
        )]
        found = c.check(claims)
        d = found[0].as_dict()
        self.assertIn("belief", d)
        self.assertIn("claim", d)


if __name__ == "__main__":
    unittest.main()
