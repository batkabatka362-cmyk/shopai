"""Knowledge gap detector tests."""
from __future__ import annotations

import unittest

from core.brain import knowledge_gap_detector as kgd


class TestConfig(unittest.TestCase):
    def test_bad_max_gaps_raises(self) -> None:
        with self.assertRaises(ValueError):
            kgd.KnowledgeGapDetector(max_gaps=0)


class TestEmpty(unittest.TestCase):
    def test_no_providers_no_gaps(self) -> None:
        d = kgd.KnowledgeGapDetector()
        report = d.detect()
        self.assertEqual(report.gaps, [])
        self.assertEqual(report.total_critical(), 0) if hasattr(
            report, "total_critical"
        ) else self.assertEqual(report.critical_count, 0)


class TestUnresolvedClaims(unittest.TestCase):
    def test_conflicted_flagged_critical(self) -> None:
        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=lambda: [
                {"subject": "p1", "predicate": "price",
                 "verdict": "conflicted"},
            ],
        )
        report = d.detect()
        self.assertEqual(len(report.gaps), 1)
        self.assertEqual(report.gaps[0].severity, "critical")

    def test_ambiguous_flagged_warning(self) -> None:
        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=lambda: [
                {"subject": "p1", "predicate": "price",
                 "verdict": "ambiguous"},
            ],
        )
        report = d.detect()
        self.assertEqual(report.gaps[0].severity, "warning")

    def test_missing_fields_skipped(self) -> None:
        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=lambda: [
                {"verdict": "conflicted"},   # no subject
            ],
        )
        self.assertEqual(d.detect().gaps, [])


class TestRepeatedProbes(unittest.TestCase):
    def test_ten_plus_repeats_critical(self) -> None:
        d = kgd.KnowledgeGapDetector(
            repeated_probes_provider=lambda: [
                {"id": "p1", "repeat_count": 15},
            ],
        )
        self.assertEqual(d.detect().gaps[0].severity, "critical")

    def test_under_three_repeats_skipped(self) -> None:
        d = kgd.KnowledgeGapDetector(
            repeated_probes_provider=lambda: [
                {"id": "p1", "repeat_count": 2},
            ],
        )
        self.assertEqual(d.detect().gaps, [])


class TestLowEvidence(unittest.TestCase):
    def test_below_quarter_critical(self) -> None:
        d = kgd.KnowledgeGapDetector(
            low_evidence_decisions_provider=lambda: [
                {"id": "d1", "evidence_score": 0.1},
            ],
        )
        self.assertEqual(d.detect().gaps[0].severity, "critical")

    def test_half_plus_skipped(self) -> None:
        d = kgd.KnowledgeGapDetector(
            low_evidence_decisions_provider=lambda: [
                {"id": "d1", "evidence_score": 0.7},
            ],
        )
        self.assertEqual(d.detect().gaps, [])


class TestStaleKnowledge(unittest.TestCase):
    def test_over_90_days_critical(self) -> None:
        d = kgd.KnowledgeGapDetector(
            stale_knowledge_provider=lambda: [
                {"subject": "p1", "predicate": "price",
                 "age_days": 120},
            ],
        )
        self.assertEqual(d.detect().gaps[0].severity, "critical")

    def test_under_30_days_skipped(self) -> None:
        d = kgd.KnowledgeGapDetector(
            stale_knowledge_provider=lambda: [
                {"subject": "p1", "predicate": "price",
                 "age_days": 10},
            ],
        )
        self.assertEqual(d.detect().gaps, [])


class TestDriftWithoutCause(unittest.TestCase):
    def test_high_psi_critical(self) -> None:
        d = kgd.KnowledgeGapDetector(
            drift_without_cause_provider=lambda: [
                {"feature": "cpm", "psi": 0.3},
            ],
        )
        self.assertEqual(d.detect().gaps[0].severity, "critical")

    def test_low_psi_skipped(self) -> None:
        d = kgd.KnowledgeGapDetector(
            drift_without_cause_provider=lambda: [
                {"feature": "cpm", "psi": 0.05},
            ],
        )
        self.assertEqual(d.detect().gaps, [])


class TestSorting(unittest.TestCase):
    def test_critical_first(self) -> None:
        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=lambda: [
                {"subject": "p1", "predicate": "name",
                 "verdict": "ambiguous"},
                {"subject": "p2", "predicate": "price",
                 "verdict": "conflicted"},
            ],
        )
        report = d.detect()
        self.assertEqual(report.gaps[0].severity, "critical")
        self.assertEqual(report.gaps[1].severity, "warning")

    def test_max_gaps_respected(self) -> None:
        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=lambda: [
                {"subject": f"p{i}", "predicate": "x",
                 "verdict": "conflicted"}
                for i in range(100)
            ],
            max_gaps=5,
        )
        self.assertEqual(len(d.detect().gaps), 5)


class TestProviderFailure(unittest.TestCase):
    def test_raising_provider_skipped(self) -> None:
        def boom():
            raise RuntimeError("x")

        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=boom,
            repeated_probes_provider=lambda: [
                {"id": "p", "repeat_count": 5},
            ],
        )
        # Second source still produces a gap
        report = d.detect()
        self.assertEqual(len(report.gaps), 1)
        self.assertEqual(report.gaps[0].source, "curiosity_engine")


class TestReport(unittest.TestCase):
    def test_count_helpers(self) -> None:
        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=lambda: [
                {"subject": "a", "predicate": "x",
                 "verdict": "conflicted"},
                {"subject": "b", "predicate": "x",
                 "verdict": "ambiguous"},
            ],
        )
        report = d.detect()
        self.assertEqual(report.critical_count, 1)
        self.assertEqual(report.warning_count, 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=lambda: [
                {"subject": "p1", "predicate": "x",
                 "verdict": "conflicted"},
            ],
        )
        report = d.detect()
        dd = report.as_dict()
        self.assertIn("gaps", dd)
        self.assertIn("total", dd)


class TestStats(unittest.TestCase):
    def test_stats_counts_providers(self) -> None:
        d = kgd.KnowledgeGapDetector(
            unresolved_claims_provider=lambda: [],
            repeated_probes_provider=lambda: [],
        )
        self.assertEqual(d.stats()["providers"], 2)


if __name__ == "__main__":
    unittest.main()
