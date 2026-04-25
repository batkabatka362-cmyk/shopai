"""Ambiguity resolver tests."""
from __future__ import annotations

import unittest

from core.brain import ambiguity_resolver as ar


class TestCandidate(unittest.TestCase):
    def test_blank_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            ar.Candidate(key="")

    def test_prior_out_of_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            ar.Candidate(key="x", prior=2.0)

    def test_negative_cost_raises(self) -> None:
        with self.assertRaises(ValueError):
            ar.Candidate(key="x", cost_of_error=-1)


class TestConfig(unittest.TestCase):
    def test_negative_weights_raise(self) -> None:
        with self.assertRaises(ValueError):
            ar.AmbiguityResolver(prior_weight=-1)

    def test_negative_margin_raises(self) -> None:
        with self.assertRaises(ValueError):
            ar.AmbiguityResolver(confident_margin=-1)


class TestResolve(unittest.TestCase):
    def setUp(self) -> None:
        self.r = ar.AmbiguityResolver()

    def test_empty_no_best(self) -> None:
        report = self.r.resolve([])
        self.assertIsNone(report.best)
        self.assertIn("no candidates", report.explain)

    def test_sole_candidate_confident(self) -> None:
        report = self.r.resolve([ar.Candidate(key="only")])
        self.assertTrue(report.confident)
        self.assertEqual(report.best.candidate.key, "only")

    def test_prior_picks_higher(self) -> None:
        cands = [
            ar.Candidate(key="high", prior=0.9),
            ar.Candidate(key="low", prior=0.2),
        ]
        report = self.r.resolve(cands)
        self.assertEqual(report.best.candidate.key, "high")

    def test_evidence_overrides_prior(self) -> None:
        cands = [
            ar.Candidate(key="prior_high", prior=0.9),
            ar.Candidate(key="evidence_high", prior=0.2),
        ]

        def favour_evidence(c):
            return 1.0 if c.key == "evidence_high" else -1.0

        report = self.r.resolve(
            cands, evaluators=[favour_evidence],
        )
        # Evidence weight = 0.6, prior weight = 0.4 → evidence wins
        self.assertEqual(report.best.candidate.key, "evidence_high")

    def test_cost_of_error_penalises(self) -> None:
        # Two candidates w/ same prior; one has huge cost of error
        cands = [
            ar.Candidate(key="safe", prior=0.5, cost_of_error=0),
            ar.Candidate(key="risky", prior=0.5, cost_of_error=100),
        ]
        report = self.r.resolve(cands)
        self.assertEqual(report.best.candidate.key, "safe")

    def test_margin_determines_confidence(self) -> None:
        # Very close scores → not confident
        cands = [
            ar.Candidate(key="a", prior=0.51),
            ar.Candidate(key="b", prior=0.5),
        ]
        report = self.r.resolve(cands)
        self.assertFalse(report.confident)

    def test_wide_margin_confident(self) -> None:
        r = ar.AmbiguityResolver(confident_margin=0.1)
        cands = [
            ar.Candidate(key="strong", prior=0.95),
            ar.Candidate(key="weak", prior=0.1),
        ]
        report = r.resolve(cands)
        self.assertTrue(report.confident)


class TestEvaluators(unittest.TestCase):
    def test_named_tuple_evaluator(self) -> None:
        def fn(c):
            return 0.5 if c.key == "a" else -0.5

        r = ar.AmbiguityResolver()
        report = r.resolve(
            [ar.Candidate(key="a"), ar.Candidate(key="b")],
            evaluators=[("context", fn)],
        )
        self.assertEqual(report.best.candidate.key, "a")

    def test_evaluator_raises_scored_zero_with_note(self) -> None:
        def boom(c):
            raise RuntimeError("x")

        r = ar.AmbiguityResolver()
        report = r.resolve(
            [ar.Candidate(key="x")],
            evaluators=[boom],
        )
        self.assertIn(
            "error",
            report.best.evaluator_notes[0],
        )

    def test_evaluator_score_clipped(self) -> None:
        def huge(c):
            return 99.0

        r = ar.AmbiguityResolver()
        report = r.resolve(
            [ar.Candidate(key="x")],
            evaluators=[huge],
        )
        # Evidence component can't exceed evidence_weight × 1
        self.assertLessEqual(
            report.best.evidence_component, 0.61,  # 0.6 + rounding slack
        )


class TestAlternatives(unittest.TestCase):
    def test_alternatives_listed(self) -> None:
        r = ar.AmbiguityResolver()
        cands = [
            ar.Candidate(key="best", prior=0.9),
            ar.Candidate(key="second", prior=0.5),
            ar.Candidate(key="third", prior=0.2),
        ]
        report = r.resolve(cands)
        self.assertEqual(
            [a.candidate.key for a in report.alternatives],
            ["second", "third"],
        )


class TestDict(unittest.TestCase):
    def test_candidate_report_serialise(self) -> None:
        r = ar.AmbiguityResolver()
        report = r.resolve([ar.Candidate(key="x")])
        d = report.as_dict()
        self.assertIn("best", d)
        self.assertIn("alternatives", d)

    def test_entry_serialises(self) -> None:
        r = ar.AmbiguityResolver()
        e = r.resolve([ar.Candidate(key="x")]).best
        self.assertIn("score", e.as_dict())

    def test_candidate_serialises(self) -> None:
        c = ar.Candidate(
            key="x", prior=0.5, metadata={"tag": "t"},
        )
        d = c.as_dict()
        self.assertEqual(d["metadata"]["tag"], "t")


class TestResolverConfig(unittest.TestCase):
    def test_config_reports(self) -> None:
        r = ar.AmbiguityResolver(
            prior_weight=0.5, evidence_weight=0.3,
            cost_weight=0.1, confident_margin=0.2,
        )
        cfg = r.config()
        self.assertEqual(cfg["prior_weight"], 0.5)
        self.assertEqual(cfg["confident_margin"], 0.2)


if __name__ == "__main__":
    unittest.main()
