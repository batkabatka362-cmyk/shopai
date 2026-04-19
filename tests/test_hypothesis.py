"""Hypothesis engine tests — predict / resolve / calibrate / stale."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core.brain import hypothesis as hy


class TestPredict(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.eng = hy.HypothesisEngine(Path(self._tmp.name) / "h.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_register_and_fetch(self) -> None:
        h = self.eng.predict(
            subject="price_bump", kpi="cvr",
            direction="down", magnitude_pct=5.0,
            horizon_days=3, baseline=0.04,
            rationale="higher price → lower CVR",
            rationale_tag="price_down",
        )
        fetched = self.eng.get(h.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.subject, "price_bump")
        self.assertEqual(fetched.direction, "down")
        self.assertEqual(fetched.verdict, "pending")

    def test_bad_direction_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.eng.predict(
                subject="x", kpi="y", direction="sideways",
                magnitude_pct=1, horizon_days=1, baseline=1.0,
            )

    def test_zero_horizon_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.eng.predict(
                subject="x", kpi="y", direction="up",
                magnitude_pct=1, horizon_days=0, baseline=1.0,
            )


class TestResolveVerdict(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.eng = hy.HypothesisEngine(Path(self._tmp.name) / "h.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _predict_up(self, baseline=100.0, mag=10.0):
        return self.eng.predict(
            subject="s", kpi="revenue", direction="up",
            magnitude_pct=mag, horizon_days=3, baseline=baseline,
        )

    def test_up_confirmed(self) -> None:
        h = self._predict_up()
        with patch("core.memory.unified_memory.get_unified_memory",
                   side_effect=RuntimeError("no mem")):
            r = self.eng.resolve(h.id, observed=115.0)
        self.assertEqual(r.verdict, "confirmed")

    def test_up_partial(self) -> None:
        h = self._predict_up()
        with patch("core.memory.unified_memory.get_unified_memory",
                   side_effect=RuntimeError("no mem")):
            r = self.eng.resolve(h.id, observed=106.0)   # +6%, half-met
        self.assertEqual(r.verdict, "partial")

    def test_up_refuted(self) -> None:
        h = self._predict_up()
        with patch("core.memory.unified_memory.get_unified_memory",
                   side_effect=RuntimeError("no mem")):
            r = self.eng.resolve(h.id, observed=101.0)   # barely moved
        self.assertEqual(r.verdict, "refuted")

    def test_down_confirmed(self) -> None:
        h = self.eng.predict(
            subject="s", kpi="cvr", direction="down",
            magnitude_pct=20.0, horizon_days=3, baseline=0.05,
        )
        with patch("core.memory.unified_memory.get_unified_memory",
                   side_effect=RuntimeError("no mem")):
            r = self.eng.resolve(h.id, observed=0.035)   # -30%
        self.assertEqual(r.verdict, "confirmed")

    def test_flat_confirmed(self) -> None:
        h = self.eng.predict(
            subject="s", kpi="aov", direction="flat",
            magnitude_pct=5.0, horizon_days=3, baseline=80.0,
        )
        with patch("core.memory.unified_memory.get_unified_memory",
                   side_effect=RuntimeError("no mem")):
            r = self.eng.resolve(h.id, observed=82.0)    # +2.5%, within band
        self.assertEqual(r.verdict, "confirmed")

    def test_unknown_id_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.eng.resolve("missing", observed=1.0)


class TestCalibration(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.eng = hy.HypothesisEngine(Path(self._tmp.name) / "h.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_two_wins_one_loss(self) -> None:
        for _ in range(2):
            h = self.eng.predict(
                subject="x", kpi="revenue", direction="up",
                magnitude_pct=10, horizon_days=3, baseline=100.0,
                rationale_tag="sales",
            )
            with patch("core.memory.unified_memory.get_unified_memory",
                       side_effect=RuntimeError("no mem")):
                self.eng.resolve(h.id, observed=115.0)  # confirmed
        h2 = self.eng.predict(
            subject="x", kpi="revenue", direction="up",
            magnitude_pct=10, horizon_days=3, baseline=100.0,
            rationale_tag="sales",
        )
        with patch("core.memory.unified_memory.get_unified_memory",
                   side_effect=RuntimeError("no mem")):
            self.eng.resolve(h2.id, observed=101.0)     # refuted
        cal = self.eng.calibration(tag="sales")
        self.assertEqual(cal.confirmed, 2)
        self.assertEqual(cal.refuted, 1)
        # Beta(3, 2) → mean = 0.6
        self.assertAlmostEqual(cal.hit_rate, 0.6, places=2)

    def test_no_data_gives_prior(self) -> None:
        cal = self.eng.calibration(tag="new_tag")
        self.assertEqual(cal.total_resolved, 0)
        self.assertAlmostEqual(cal.hit_rate, 0.5, places=2)


class TestPendingListings(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.eng = hy.HypothesisEngine(Path(self._tmp.name) / "h.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_pending_filters_by_subject(self) -> None:
        self.eng.predict(subject="a", kpi="k", direction="up",
                         magnitude_pct=1, horizon_days=1, baseline=1.0)
        self.eng.predict(subject="b", kpi="k", direction="up",
                         magnitude_pct=1, horizon_days=1, baseline=1.0)
        a_list = self.eng.list_pending(subject="a")
        self.assertEqual(len(a_list), 1)
        self.assertEqual(a_list[0].subject, "a")

    def test_list_pending_all(self) -> None:
        for i in range(3):
            self.eng.predict(subject=f"s{i}", kpi="k", direction="up",
                             magnitude_pct=1, horizon_days=1, baseline=1.0)
        self.assertEqual(len(self.eng.list_pending()), 3)


class TestStaleness(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.eng = hy.HypothesisEngine(Path(self._tmp.name) / "h.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_mark_stale_promotes_old_pending(self) -> None:
        # Backdate via direct SQL.
        h = self.eng.predict(
            subject="x", kpi="k", direction="up",
            magnitude_pct=1, horizon_days=1, baseline=1.0,
        )
        import sqlite3
        conn = sqlite3.connect(str(self.eng._db))
        # Set created_at to 3 days ago (horizon=1, so >2× = stale).
        conn.execute("UPDATE hypotheses SET created_at=? WHERE id=?",
                     (time.time() - 3 * 86_400, h.id))
        conn.commit()
        conn.close()
        n = self.eng.mark_stale()
        self.assertEqual(n, 1)
        fetched = self.eng.get(h.id)
        self.assertEqual(fetched.verdict, "stale")


class TestFromDecision(unittest.TestCase):
    def test_scale_decision_becomes_up_hypothesis(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        hy._ENGINE = hy.HypothesisEngine(Path(tmp.name) / "h.db")
        try:
            h = hy.hypothesise_from_decision(
                decision={"verdict": "scale", "subject": "sku-1",
                          "rationale": "prev ROAS high"},
                expected_kpi="revenue",
                baseline=500.0,
                horizon_days=7,
            )
            self.assertEqual(h.direction, "up")
            self.assertEqual(h.rationale_tag, "scale")
        finally:
            hy._ENGINE = None
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
