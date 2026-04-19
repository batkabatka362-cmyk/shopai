"""Belief state — Beta / Gauss conjugate-update tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import belief_state as bs


class TestBetaDist(unittest.TestCase):
    def test_default_mean_half(self) -> None:
        d = bs.BetaDist()
        self.assertAlmostEqual(d.mean, 0.5)
        self.assertAlmostEqual(d.stddev, 1 / (2 * (3 ** 0.5)), places=3)

    def test_update_moves_mean(self) -> None:
        d = bs.BetaDist()
        for _ in range(10):
            d.update(success=True)
        self.assertGreater(d.mean, 0.9)

    def test_credible_interval_narrows(self) -> None:
        d = bs.BetaDist()
        wide = d.credible_interval(0.95)
        for _ in range(40):
            d.update(success=True)
        narrow = d.credible_interval(0.95)
        self.assertLess(narrow[1] - narrow[0], wide[1] - wide[0])


class TestGaussDist(unittest.TestCase):
    def test_welford_matches_statistics(self) -> None:
        import statistics
        values = [3.2, 5.0, 2.1, 4.4, 3.8, 6.0]
        d = bs.GaussDist()
        for v in values:
            d.update(v)
        self.assertAlmostEqual(d.mean, statistics.fmean(values), places=5)
        self.assertAlmostEqual(d.stddev, statistics.stdev(values), places=5)

    def test_ci_collapses_below_two_samples(self) -> None:
        d = bs.GaussDist()
        d.update(3.0)
        lo, hi = d.credible_interval()
        self.assertEqual((lo, hi), (3.0, 3.0))


class TestBeliefStore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = bs.BeliefStore(Path(self._tmp.name) / "b.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_beta_update_persists(self) -> None:
        for _ in range(5):
            self.store.beta_update("predictor.x", success=True)
        d = self.store.get("predictor.x")
        self.assertEqual(d["kind"], "beta")
        self.assertGreater(d["mean"], 0.7)

    def test_gauss_update_persists(self) -> None:
        for v in [2, 4, 6, 8, 10]:
            self.store.gauss_update("roas.electronics", v)
        d = self.store.get("roas.electronics")
        self.assertEqual(d["kind"], "gauss")
        self.assertAlmostEqual(d["mean"], 6.0)
        self.assertEqual(d["n"], 5)

    def test_credible_interval(self) -> None:
        for _ in range(50):
            self.store.beta_update("p", success=True)
        for _ in range(5):
            self.store.beta_update("p", success=False)
        lo, hi = self.store.credible_interval("p", ci=0.8)
        self.assertLess(lo, hi)
        self.assertGreater(hi, 0.8)

    def test_list_names_with_prefix(self) -> None:
        self.store.beta_update("foo.a", True)
        self.store.beta_update("foo.b", True)
        self.store.gauss_update("bar.c", 1.0)
        self.assertEqual(self.store.list_names("foo."), ["foo.a", "foo.b"])

    def test_reset_removes_entry(self) -> None:
        self.store.beta_update("p", True)
        self.assertTrue(self.store.reset("p"))
        self.assertIsNone(self.store.get("p"))
        self.assertFalse(self.store.reset("nonexistent"))


if __name__ == "__main__":
    unittest.main()
