"""Surprise detector tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import surprise as sp


class TestOutlierDetection(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.d = sp.SurpriseDetector(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_3_sigma_is_surprising(self) -> None:
        # Pre-warm the signature past novelty window so novel path
        # doesn't fire.
        for _ in range(4):
            self.d.observe("roas:audio",
                            observed=2.0, expected_mean=2.0,
                            expected_stdev=0.5)
        # 4 sigma above mean
        ev = self.d.observe("roas:audio",
                             observed=4.0, expected_mean=2.0,
                             expected_stdev=0.5)
        self.assertIsNotNone(ev)
        self.assertEqual(ev.kind, "outlier")
        self.assertGreater(abs(ev.z_score), 3)

    def test_within_band_is_not_surprising(self) -> None:
        for _ in range(4):
            self.d.observe("cvr:audio",
                            observed=0.05, expected_mean=0.05,
                            expected_stdev=0.01)
        ev = self.d.observe("cvr:audio",
                             observed=0.055, expected_mean=0.05,
                             expected_stdev=0.01)
        self.assertIsNone(ev)

    def test_zero_stdev_degrades_to_novelty(self) -> None:
        ev = self.d.observe("new_sig",
                             observed=5.0, expected_mean=5.0,
                             expected_stdev=0.0)
        # First-time + no usable band → novelty path
        self.assertIsNotNone(ev)
        self.assertEqual(ev.kind, "novel")


class TestNovelty(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.d = sp.SurpriseDetector(Path(self._tmp.name) / "s.db",
                                      novel_until=2)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_first_sighting_flagged(self) -> None:
        ev = self.d.observe("brand_new:sig")
        self.assertIsNotNone(ev)
        self.assertEqual(ev.kind, "novel")

    def test_after_threshold_no_longer_novel(self) -> None:
        self.d.observe("s1")
        self.d.observe("s1")
        ev = self.d.observe("s1")   # 3rd sighting, novel_until=2
        self.assertIsNone(ev)


class TestFollowupQueue(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.d = sp.SurpriseDetector(Path(self._tmp.name) / "s.db",
                                      novel_until=0)   # no novelty path

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_pending_queue_sorted_by_magnitude(self) -> None:
        for _ in range(3):
            self.d.observe("x", observed=2.0, expected_mean=2.0,
                            expected_stdev=0.5)
        self.d.observe("x", observed=5.0, expected_mean=2.0,
                        expected_stdev=0.5)     # +6σ
        self.d.observe("x", observed=3.0, expected_mean=2.0,
                        expected_stdev=0.5)     # +2σ
        pending = self.d.pending_followups()
        self.assertGreater(len(pending), 0)
        # Highest-magnitude entry should come first.
        self.assertGreaterEqual(
            pending[0].magnitude, pending[-1].magnitude,
        )

    def test_resolve_removes_from_pending(self) -> None:
        for _ in range(3):
            self.d.observe("x", observed=1.0, expected_mean=1.0,
                            expected_stdev=0.3)
        ev = self.d.observe("x", observed=5.0, expected_mean=1.0,
                             expected_stdev=0.3)
        self.assertIsNotNone(ev)
        self.d.resolve(ev.id, note="debated")
        pending = self.d.pending_followups()
        self.assertTrue(all(p.id != ev.id for p in pending))

    def test_dismiss_changes_state(self) -> None:
        for _ in range(3):
            self.d.observe("x", observed=1.0, expected_mean=1.0,
                            expected_stdev=0.3)
        ev = self.d.observe("x", observed=5.0, expected_mean=1.0,
                             expected_stdev=0.3)
        self.d.dismiss(ev.id)
        pending = self.d.pending_followups()
        self.assertTrue(all(p.id != ev.id for p in pending))


class TestSummary(unittest.TestCase):
    def test_summary_counts(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = sp.SurpriseDetector(Path(tmp.name) / "s.db")
        d.observe("s1")   # novel
        d.observe("s2")   # novel
        summary = d.summary()
        self.assertGreaterEqual(summary["total_surprises"], 2)
        self.assertGreaterEqual(summary["pending_followups"], 2)
        tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
