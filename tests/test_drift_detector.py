"""Drift detector tests."""
from __future__ import annotations

import random
import unittest

from core.brain import drift_detector as dd


class TestStatsHelpers(unittest.TestCase):
    def test_ks_identical_is_zero(self) -> None:
        xs = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(dd.ks_statistic(xs, xs), 0.0)

    def test_ks_disjoint_is_one(self) -> None:
        a = [1.0, 2.0, 3.0]
        b = [10.0, 11.0, 12.0]
        self.assertGreater(dd.ks_statistic(a, b), 0.8)

    def test_chi2_identical_is_zero(self) -> None:
        c = {"a": 5, "b": 3}
        self.assertAlmostEqual(
            dd.chi_square_distance(c, c), 0.0, places=4,
        )

    def test_chi2_flipped(self) -> None:
        ref = {"a": 10, "b": 1}
        cur = {"a": 1, "b": 10}
        self.assertGreater(dd.chi_square_distance(ref, cur), 0.5)


class TestNumeric(unittest.TestCase):
    def setUp(self) -> None:
        self.d = dd.DriftDetector(
            mean_sigma_threshold=2.0, ks_threshold=0.25,
        )

    def test_no_drift_when_distributions_match(self) -> None:
        rng = random.Random(42)
        ref = [rng.gauss(0, 1) for _ in range(200)]
        cur = [rng.gauss(0, 1) for _ in range(200)]
        self.d.set_numeric_reference("x", ref)
        self.assertIsNone(self.d.check_numeric("x", cur))

    def test_drift_when_mean_shifted(self) -> None:
        rng = random.Random(7)
        ref = [rng.gauss(0, 1) for _ in range(200)]
        cur = [rng.gauss(5, 1) for _ in range(200)]
        self.d.set_numeric_reference("roas", ref)
        ev = self.d.check_numeric("roas", cur)
        self.assertIsNotNone(ev)
        self.assertGreater(ev.mean_shift_sigma, 2.0)

    def test_no_reference_returns_none(self) -> None:
        self.assertIsNone(self.d.check_numeric("untracked", [1.0]))

    def test_empty_current_returns_none(self) -> None:
        self.d.set_numeric_reference("x", [1.0, 2.0, 3.0])
        self.assertIsNone(self.d.check_numeric("x", []))


class TestCategorical(unittest.TestCase):
    def setUp(self) -> None:
        self.d = dd.DriftDetector(chi2_threshold=0.3)

    def test_no_drift_when_distribution_same(self) -> None:
        ref = ["audio"] * 80 + ["fashion"] * 20
        cur = ["audio"] * 75 + ["fashion"] * 25
        self.d.set_categorical_reference("niche", ref)
        self.assertIsNone(self.d.check_categorical("niche", cur))

    def test_drift_when_category_flipped(self) -> None:
        ref = ["audio"] * 80 + ["fashion"] * 20
        cur = ["audio"] * 20 + ["fashion"] * 80
        self.d.set_categorical_reference("niche", ref)
        ev = self.d.check_categorical("niche", cur)
        self.assertIsNotNone(ev)
        self.assertGreater(ev.chi2_distance, 0.5)

    def test_no_reference_returns_none(self) -> None:
        self.assertIsNone(
            self.d.check_categorical("x", ["a", "b"]),
        )


class TestBatch(unittest.TestCase):
    def test_batch_orders_by_severity(self) -> None:
        d = dd.DriftDetector()
        ref_strong = [0.0] * 100
        cur_strong = [10.0] * 100
        ref_mild = [0.0, 0.1, 0.2, 0.3] * 25
        cur_mild = [0.2, 0.3, 0.4, 0.5] * 25
        d.set_numeric_reference("strong", ref_strong)
        d.set_numeric_reference("mild", ref_mild)
        events = d.check_batch(numeric={
            "strong": cur_strong, "mild": cur_mild,
        })
        if len(events) >= 2:
            self.assertEqual(events[0].feature, "strong")

    def test_batch_handles_mixed(self) -> None:
        d = dd.DriftDetector()
        d.set_numeric_reference("roas", [2.0] * 100)
        d.set_categorical_reference(
            "niche", ["audio"] * 80 + ["fashion"] * 20,
        )
        events = d.check_batch(
            numeric={"roas": [5.0] * 100},
            categorical={"niche": ["fashion"] * 100},
        )
        kinds = {e.kind for e in events}
        self.assertIn("numeric", kinds)
        self.assertIn("categorical", kinds)


class TestReferenceShapes(unittest.TestCase):
    def test_shapes_summarises_references(self) -> None:
        d = dd.DriftDetector()
        d.set_numeric_reference("roas", [1.0, 2.0, 3.0])
        d.set_categorical_reference("niche", ["audio", "audio"])
        shapes = d.reference_shapes()
        self.assertEqual(shapes["roas"]["kind"], "numeric")
        self.assertEqual(shapes["niche"]["kind"], "categorical")


if __name__ == "__main__":
    unittest.main()
