"""Uplift estimator tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import uplift_estimator as ue


class TestObserve(unittest.TestCase):
    def test_observe_blank_raises(self) -> None:
        e = ue.UpliftEstimator()
        with self.assertRaises(ValueError):
            e.observe("", {}, {"y": 1})

    def test_observe_accumulates(self) -> None:
        e = ue.UpliftEstimator()
        e.observe("A", {}, {"y": 1})
        e.observe("B", {}, {"y": 2})
        self.assertEqual(e.stats()["n_observations"], 2)
        self.assertEqual(e.stats()["distinct_treatments"], 2)


class TestATEBinary(unittest.TestCase):
    def test_no_effect_ate_near_zero(self) -> None:
        e = ue.UpliftEstimator()
        for _ in range(50):
            e.observe("A", {}, {"cvr": 0.10})
            e.observe("B", {}, {"cvr": 0.10})
        est = e.ate(
            treatment_value="A", control_value="B",
            outcome_key="cvr",
        )
        self.assertAlmostEqual(est.ate, 0.0)
        self.assertFalse(est.significant)

    def test_positive_effect_ate_positive(self) -> None:
        e = ue.UpliftEstimator()
        for _ in range(50):
            e.observe("A", {}, {"cvr": 0.20})
            e.observe("B", {}, {"cvr": 0.10})
        est = e.ate(
            treatment_value="A", control_value="B",
            outcome_key="cvr",
        )
        self.assertAlmostEqual(est.ate, 0.10, places=3)
        # Zero-variance case: CI is exactly the estimate → significant
        self.assertTrue(est.significant)

    def test_returns_counts(self) -> None:
        e = ue.UpliftEstimator()
        for _ in range(3):
            e.observe("A", {}, {"y": 1})
        for _ in range(5):
            e.observe("B", {}, {"y": 0})
        est = e.ate(
            treatment_value="A", control_value="B",
            outcome_key="y",
        )
        self.assertEqual(est.n_treatment, 3)
        self.assertEqual(est.n_control, 5)


class TestSignificance(unittest.TestCase):
    def test_noisy_similar_means_not_significant(self) -> None:
        import random
        random.seed(42)
        e = ue.UpliftEstimator()
        for _ in range(30):
            e.observe("A", {}, {"y": random.gauss(1.0, 1.0)})
            e.observe("B", {}, {"y": random.gauss(1.0, 1.0)})
        est = e.ate(
            treatment_value="A", control_value="B",
            outcome_key="y",
        )
        self.assertFalse(est.significant)

    def test_large_separation_significant(self) -> None:
        import random
        random.seed(42)
        e = ue.UpliftEstimator()
        for _ in range(100):
            e.observe("A", {}, {"y": random.gauss(5.0, 0.5)})
            e.observe("B", {}, {"y": random.gauss(1.0, 0.5)})
        est = e.ate(
            treatment_value="A", control_value="B",
            outcome_key="y",
        )
        self.assertTrue(est.significant)
        self.assertGreater(est.ate, 3.5)


class TestCATE(unittest.TestCase):
    def test_cate_filters_to_subgroup(self) -> None:
        e = ue.UpliftEstimator()
        # Overall no effect, but +0.2 effect among niche=audio
        for _ in range(20):
            e.observe("A", {"niche": "audio"}, {"cvr": 0.3})
            e.observe("B", {"niche": "audio"}, {"cvr": 0.1})
            e.observe("A", {"niche": "fashion"}, {"cvr": 0.1})
            e.observe("B", {"niche": "fashion"}, {"cvr": 0.1})
        audio = e.cate(
            treatment_value="A", control_value="B",
            outcome_key="cvr",
            covariates_subset={"niche": "audio"},
        )
        self.assertAlmostEqual(audio.ate, 0.2, places=3)
        fashion = e.cate(
            treatment_value="A", control_value="B",
            outcome_key="cvr",
            covariates_subset={"niche": "fashion"},
        )
        self.assertAlmostEqual(fashion.ate, 0.0, places=3)

    def test_subgroup_with_no_matches_empty(self) -> None:
        e = ue.UpliftEstimator()
        e.observe("A", {"x": 1}, {"y": 1})
        est = e.cate(
            treatment_value="A", control_value="B",
            outcome_key="y",
            covariates_subset={"x": 99},
        )
        self.assertEqual(est.n_treatment, 0)


class TestBestTreatment(unittest.TestCase):
    def test_highest_ate_picked(self) -> None:
        e = ue.UpliftEstimator()
        for _ in range(10):
            e.observe("ctrl", {}, {"y": 1.0})
            e.observe("mild", {}, {"y": 1.2})
            e.observe("strong", {}, {"y": 2.0})
            e.observe("weak", {}, {"y": 0.5})
        best = e.best_treatment(
            control_value="ctrl",
            outcome_key="y",
            candidates=["mild", "strong", "weak"],
            min_samples=5,
        )
        self.assertEqual(best.treatment_value, "strong")

    def test_min_samples_filters_out(self) -> None:
        e = ue.UpliftEstimator()
        e.observe("strong", {}, {"y": 5})   # only 1 sample
        for _ in range(10):
            e.observe("mild", {}, {"y": 2})
            e.observe("ctrl", {}, {"y": 1})
        best = e.best_treatment(
            control_value="ctrl",
            outcome_key="y",
            candidates=["strong", "mild"],
            min_samples=5,
        )
        self.assertEqual(best.treatment_value, "mild")

    def test_no_candidates_returns_none(self) -> None:
        e = ue.UpliftEstimator()
        self.assertIsNone(e.best_treatment(
            control_value="x", outcome_key="y", candidates=[],
        ))


class TestPersistence(unittest.TestCase):
    def test_persisted_to_sqlite(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        e = ue.UpliftEstimator(db_path=Path(tmp.name) / "u.db")
        for _ in range(5):
            e.observe("A", {}, {"y": 1})
        self.assertEqual(e.stats()["n_observations"], 5)
        e.close()
        tmp.cleanup()


class TestClear(unittest.TestCase):
    def test_clear_empties(self) -> None:
        e = ue.UpliftEstimator()
        e.observe("A", {}, {"y": 1})
        n = e.clear()
        self.assertEqual(n, 1)
        self.assertEqual(e.stats()["n_observations"], 0)


class TestDict(unittest.TestCase):
    def test_estimate_as_dict(self) -> None:
        e = ue.UpliftEstimator()
        for _ in range(5):
            e.observe("A", {}, {"y": 2})
            e.observe("B", {}, {"y": 1})
        est = e.ate(
            treatment_value="A", control_value="B",
            outcome_key="y",
        )
        d = est.as_dict()
        self.assertIn("ate", d)
        self.assertIn("n_treatment", d)


if __name__ == "__main__":
    unittest.main()
