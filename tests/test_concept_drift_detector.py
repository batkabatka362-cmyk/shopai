"""Concept drift detector tests."""
from __future__ import annotations

import random
import unittest

from core.memory import concept_drift_detector as cd


class TestPSIMath(unittest.TestCase):
    def test_identical_distributions_zero_psi(self) -> None:
        a = {"q1": 100, "q2": 100, "q3": 100}
        psi, _ = cd._psi(a, a)
        self.assertAlmostEqual(psi, 0.0, places=6)

    def test_completely_different_high_psi(self) -> None:
        a = {"q1": 100}
        b = {"q2": 100}
        psi, _ = cd._psi(a, b)
        self.assertGreater(psi, 0.5)

    def test_small_shift_low_psi(self) -> None:
        a = {"q1": 50, "q2": 50}
        b = {"q1": 55, "q2": 45}
        psi, _ = cd._psi(a, b)
        self.assertGreater(psi, 0.0)
        self.assertLess(psi, 0.1)


class TestSeverity(unittest.TestCase):
    def test_none(self) -> None:
        self.assertEqual(cd._severity(0.05), "none")

    def test_moderate(self) -> None:
        self.assertEqual(cd._severity(0.15), "moderate")

    def test_significant(self) -> None:
        self.assertEqual(cd._severity(0.25), "significant")


class TestQuantileBins(unittest.TestCase):
    def test_bins_monotonic(self) -> None:
        edges = cd._quantile_edges(list(range(100)), n_bins=5)
        self.assertEqual(edges, sorted(edges))

    def test_ties_deduped(self) -> None:
        edges = cd._quantile_edges([5] * 20, n_bins=5)
        # All values 5 → edges collapse to at most one entry
        self.assertLessEqual(len(edges), 1)


class TestNumericDrift(unittest.TestCase):
    def test_stable_distribution_no_drift(self) -> None:
        random.seed(42)
        d = cd.ConceptDriftDetector(min_baseline=20, min_recent=20)
        # PSI is noisy at small N; use a larger sample for stability
        for _ in range(2000):
            d.observe_numeric("cpm", random.gauss(5, 1), phase="baseline")
        for _ in range(2000):
            d.observe_numeric("cpm", random.gauss(5, 1), phase="recent")
        r = d.check("cpm")
        self.assertEqual(r.kind, "numeric")
        self.assertEqual(r.severity, "none")

    def test_mean_shift_flagged(self) -> None:
        random.seed(42)
        d = cd.ConceptDriftDetector(min_baseline=20, min_recent=20)
        for _ in range(200):
            d.observe_numeric("cpm", random.gauss(5, 1), phase="baseline")
        for _ in range(100):
            d.observe_numeric("cpm", random.gauss(12, 1), phase="recent")
        r = d.check("cpm")
        self.assertIn(r.severity, ("moderate", "significant"))

    def test_insufficient_data(self) -> None:
        d = cd.ConceptDriftDetector(min_baseline=100, min_recent=50)
        d.observe_numeric("cpm", 5.0, phase="baseline")
        r = d.check("cpm")
        self.assertEqual(r.kind, "insufficient")


class TestCategoricalDrift(unittest.TestCase):
    def test_stable_no_drift(self) -> None:
        d = cd.ConceptDriftDetector(min_baseline=20, min_recent=20)
        for _ in range(100):
            d.observe_categorical("channel", "fb", phase="baseline")
        for _ in range(30):
            d.observe_categorical("channel", "fb", phase="recent")
        r = d.check("channel")
        self.assertEqual(r.severity, "none")

    def test_new_dominant_class_flagged(self) -> None:
        d = cd.ConceptDriftDetector(min_baseline=20, min_recent=20)
        for _ in range(100):
            d.observe_categorical("channel", "fb", phase="baseline")
        for _ in range(60):
            d.observe_categorical("channel", "tiktok", phase="recent")
        r = d.check("channel")
        self.assertIn(r.severity, ("moderate", "significant"))


class TestCheckAll(unittest.TestCase):
    def test_sorted_by_psi_desc(self) -> None:
        random.seed(42)
        d = cd.ConceptDriftDetector(min_baseline=10, min_recent=10)
        for _ in range(30):
            d.observe_numeric("stable", random.gauss(5, 1), phase="baseline")
            d.observe_numeric("stable", random.gauss(5, 1), phase="recent")
            d.observe_numeric(
                "shifted", random.gauss(5, 1), phase="baseline",
            )
            d.observe_numeric(
                "shifted", random.gauss(15, 1), phase="recent",
            )
        reports = d.check_all()
        self.assertEqual(reports[0].feature, "shifted")


class TestReset(unittest.TestCase):
    def test_reset_single(self) -> None:
        d = cd.ConceptDriftDetector(min_baseline=10, min_recent=5)
        d.observe_numeric("a", 1.0, phase="baseline")
        d.observe_numeric("b", 1.0, phase="baseline")
        d.reset("a")
        self.assertNotIn("a", d.features())
        self.assertIn("b", d.features())

    def test_reset_all(self) -> None:
        d = cd.ConceptDriftDetector(min_baseline=10, min_recent=5)
        d.observe_numeric("a", 1.0, phase="baseline")
        d.observe_categorical("b", "x", phase="baseline")
        d.reset()
        self.assertEqual(d.features(), [])


class TestConfig(unittest.TestCase):
    def test_bad_config_raises(self) -> None:
        with self.assertRaises(ValueError):
            cd.ConceptDriftDetector(min_baseline=-1)
        with self.assertRaises(ValueError):
            cd.ConceptDriftDetector(n_bins=1)

    def test_bad_phase_raises(self) -> None:
        d = cd.ConceptDriftDetector()
        with self.assertRaises(ValueError):
            d.observe_numeric("x", 1.0, phase="invalid")


class TestSummary(unittest.TestCase):
    def test_summary_shape(self) -> None:
        random.seed(42)
        d = cd.ConceptDriftDetector(min_baseline=10, min_recent=10)
        for _ in range(30):
            d.observe_numeric("cpm", random.gauss(5, 1), phase="baseline")
            d.observe_numeric("cpm", random.gauss(15, 1), phase="recent")
        s = d.summary()
        self.assertIn("features_tracked", s)
        self.assertIn("shifted", s)
        self.assertIn("worst_psi", s)
        self.assertEqual(s["features_tracked"], 1)


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        d = cd.ConceptDriftDetector()
        r = d.check("nobody")
        self.assertEqual(r.kind, "insufficient")
        rd = r.as_dict()
        self.assertIn("severity", rd)


if __name__ == "__main__":
    unittest.main()
