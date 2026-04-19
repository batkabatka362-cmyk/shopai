"""Competence model tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import competence_model as cm


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = cm.CompetenceModel(Path(self._tmp.name) / "cm.db")

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_record_creates_row(self) -> None:
        self.m.record("kill_ad", success=True)
        c = self.m.competence("kill_ad")
        self.assertEqual(c.uses, 1)
        self.assertEqual(c.wins, 1)

    def test_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.m.record("", success=True)

    def test_multiple_records_accumulate(self) -> None:
        for _ in range(5):
            self.m.record("x", success=True)
        for _ in range(5):
            self.m.record("x", success=False)
        c = self.m.competence("x")
        self.assertEqual(c.uses, 10)
        self.assertEqual(c.wins, 5)

    def test_stated_confidence_tracked(self) -> None:
        self.m.record("x", success=True, stated_confidence=0.8)
        self.m.record("x", success=False, stated_confidence=0.9)
        c = self.m.competence("x")
        self.assertAlmostEqual(c.mean_stated_confidence, 0.85)


class TestCompetence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = cm.CompetenceModel(Path(self._tmp.name) / "cm.db")

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_unknown_class_returns_uniform_prior(self) -> None:
        c = self.m.competence("nobody")
        self.assertEqual(c.uses, 0)
        self.assertEqual(c.success_rate, 0.5)

    def test_beta_posterior_pulls_toward_mean(self) -> None:
        self.m.record("x", success=True)
        c = self.m.competence("x")
        self.assertLess(c.success_rate, 1.0)
        self.assertGreater(c.success_rate, 0.5)

    def test_strong_evidence_dominates_prior(self) -> None:
        for _ in range(100):
            self.m.record("x", success=True)
        c = self.m.competence("x")
        self.assertGreater(c.success_rate, 0.95)


class TestShouldDefer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = cm.CompetenceModel(Path(self._tmp.name) / "cm.db")

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_novel_task_defers(self) -> None:
        self.assertTrue(self.m.should_defer("brand_new"))

    def test_weak_task_defers(self) -> None:
        for _ in range(10):
            self.m.record("weak", success=False)
        self.assertTrue(self.m.should_defer("weak", threshold=0.5))

    def test_strong_task_no_defer(self) -> None:
        for _ in range(10):
            self.m.record("strong", success=True)
        self.assertFalse(self.m.should_defer("strong", threshold=0.5))


class TestCalibration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.m = cm.CompetenceModel(Path(self._tmp.name) / "cm.db")

    def tearDown(self) -> None:
        self.m.close()
        self._tmp.cleanup()

    def test_overconfident_pattern_flagged(self) -> None:
        for _ in range(20):
            self.m.record("x", success=True, stated_confidence=0.9)
        for _ in range(20):
            self.m.record("x", success=False, stated_confidence=0.9)
        c = self.m.competence("x")
        self.assertGreater(c.calibration_error, 0.3)

    def test_underconfident_pattern_flagged(self) -> None:
        for _ in range(30):
            self.m.record("x", success=True, stated_confidence=0.4)
        c = self.m.competence("x")
        self.assertLess(c.calibration_error, -0.3)

    def test_global_gap_measures(self) -> None:
        for _ in range(10):
            self.m.record("a", success=True, stated_confidence=0.9)
        for _ in range(10):
            self.m.record("b", success=False, stated_confidence=0.8)
        gap = self.m.confidence_gap(min_support=3)
        self.assertGreater(gap["mean_abs_gap"], 0.0)
        self.assertGreater(gap["global_bias"], 0.0)


class TestRank(unittest.TestCase):
    def test_rank_by_success_rate(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CompetenceModel(Path(tmp.name) / "cm.db")
        for _ in range(10):
            m.record("a", success=True)
        for _ in range(10):
            m.record("b", success=False)
        for _ in range(5):
            m.record("c", success=True)
        for _ in range(5):
            m.record("c", success=False)
        ranked = m.rank(min_support=3)
        self.assertEqual(ranked[0].task_class, "a")
        self.assertEqual(ranked[-1].task_class, "b")
        m.close()
        tmp.cleanup()

    def test_rank_below_min_support_excluded(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CompetenceModel(Path(tmp.name) / "cm.db")
        m.record("only_one", success=True)
        ranked = m.rank(min_support=3)
        self.assertEqual(ranked, [])
        m.close()
        tmp.cleanup()


class TestStrengthsWeaknesses(unittest.TestCase):
    def test_partition(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CompetenceModel(Path(tmp.name) / "cm.db")
        for _ in range(10):
            m.record("a", success=True)
        for _ in range(10):
            m.record("b", success=False)
        sw = m.strengths_weaknesses(top_n=1, min_support=3)
        self.assertEqual(sw["strengths"][0]["task_class"], "a")
        self.assertEqual(sw["weaknesses"][0]["task_class"], "b")
        m.close()
        tmp.cleanup()


class TestSummary(unittest.TestCase):
    def test_empty_summary(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CompetenceModel(Path(tmp.name) / "cm.db")
        s = m.summary()
        self.assertEqual(s["task_classes"], 0)
        self.assertEqual(s["total_uses"], 0)
        m.close()
        tmp.cleanup()

    def test_populated_summary(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        m = cm.CompetenceModel(Path(tmp.name) / "cm.db")
        for _ in range(3):
            m.record("a", success=True)
        s = m.summary()
        self.assertEqual(s["task_classes"], 1)
        self.assertEqual(s["total_uses"], 3)
        m.close()
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
