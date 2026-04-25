"""Revenue funnel tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import revenue_funnel as rf


class TestRecord(unittest.TestCase):
    def test_bad_stage_raises(self) -> None:
        f = rf.RevenueFunnel()
        with self.assertRaises(ValueError):
            f.record("bogus")

    def test_bad_count_raises(self) -> None:
        f = rf.RevenueFunnel()
        with self.assertRaises(ValueError):
            f.record("impression", 0)

    def test_record_increments(self) -> None:
        f = rf.RevenueFunnel()
        f.record("impression", 100)
        f.record("impression", 50)
        s = f.stats()
        self.assertEqual(s["counts"]["impression"], 150)

    def test_record_batch(self) -> None:
        f = rf.RevenueFunnel()
        n = f.record_batch({
            "impression": 100, "click": 10, "purchase": 2,
        })
        self.assertEqual(n, 112)


class TestAnalyse(unittest.TestCase):
    def setUp(self) -> None:
        self.f = rf.RevenueFunnel()

    def test_no_data_biggest_leak_none(self) -> None:
        snap = self.f.analyse()
        self.assertEqual(snap.overall_conversion, 0.0)
        self.assertEqual(snap.return_rate, 0.0)

    def test_identifies_biggest_leak(self) -> None:
        # big drop between click→view_product (99 lost)
        self.f.record_batch({
            "impression": 1000, "click": 100, "view_product": 1,
            "add_to_cart": 1, "checkout": 1, "purchase": 1,
        })
        snap = self.f.analyse()
        # impression→click drops 900, biggest
        self.assertEqual(snap.biggest_leak, ("impression", "click"))
        self.assertIn("CTR", snap.biggest_leak_diagnosis)

    def test_checkout_leak(self) -> None:
        # Everything funnels evenly until checkout drops 80%
        self.f.record_batch({
            "impression": 1000, "click": 500, "view_product": 400,
            "add_to_cart": 300, "checkout": 250, "purchase": 50,
        })
        snap = self.f.analyse()
        self.assertEqual(snap.biggest_leak, ("impression", "click"))
        # impression→click drops 500 (largest absolute)
        # overall_conversion = 50/1000 = 0.05
        self.assertAlmostEqual(snap.overall_conversion, 0.05, places=4)

    def test_return_rate(self) -> None:
        self.f.record_batch({
            "impression": 100, "click": 10, "view_product": 10,
            "add_to_cart": 10, "checkout": 10, "purchase": 10,
            "return": 2,
        })
        snap = self.f.analyse()
        self.assertAlmostEqual(snap.return_rate, 0.2, places=4)

    def test_stage_metrics(self) -> None:
        self.f.record_batch({
            "impression": 1000, "click": 100,
        })
        snap = self.f.analyse()
        by_stage = {m.stage: m for m in snap.stages}
        self.assertEqual(by_stage["impression"].count, 1000)
        self.assertAlmostEqual(
            by_stage["impression"].conversion_to_next, 0.1, places=4,
        )
        self.assertEqual(by_stage["impression"].drop_count, 900)

    def test_zero_impressions_overall_cvr_zero(self) -> None:
        self.f.record("purchase", 5)
        snap = self.f.analyse()
        self.assertEqual(snap.overall_conversion, 0.0)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "f.db"
        first = rf.RevenueFunnel(path)
        first.record_batch({"impression": 100, "click": 5})
        first.close()
        second = rf.RevenueFunnel(path)
        s = second.stats()
        self.assertEqual(s["counts"]["impression"], 100)
        self.assertEqual(s["counts"]["click"], 5)
        second.close()
        tmp.cleanup()


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        f = rf.RevenueFunnel()
        f.record("impression", 50)
        n = f.reset()
        self.assertEqual(n, 50)
        self.assertEqual(f.stats()["total_events"], 0)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        f = rf.RevenueFunnel()
        f.record("click", 3)
        s = f.stats()
        self.assertEqual(s["total_events"], 3)
        self.assertIn("counts", s)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        f = rf.RevenueFunnel()
        f.record_batch({"impression": 100, "click": 10, "purchase": 1})
        snap = f.analyse()
        d = snap.as_dict()
        self.assertIn("stages", d)
        self.assertIn("biggest_leak", d)
        self.assertIn("overall_conversion", d)


if __name__ == "__main__":
    unittest.main()
