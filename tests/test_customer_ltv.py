"""Customer LTV tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import customer_ltv as cl


class TestObserve(unittest.TestCase):
    def test_blank_id_raises(self) -> None:
        e = cl.CustomerLTV()
        with self.assertRaises(ValueError):
            e.observe("", order_value=10)

    def test_negative_values_raise(self) -> None:
        e = cl.CustomerLTV()
        with self.assertRaises(ValueError):
            e.observe("c", order_value=-1)
        with self.assertRaises(ValueError):
            e.observe("c", order_value=10, refund_value=-1)

    def test_invalid_silent_weeks_raises(self) -> None:
        with self.assertRaises(ValueError):
            cl.CustomerLTV(churn_silent_weeks=0)

    def test_observe_creates_profile(self) -> None:
        e = cl.CustomerLTV()
        e.observe("c1", order_value=20.0)
        prof = e.profile("c1")
        self.assertEqual(prof.n_orders, 1)
        self.assertEqual(prof.total_spend, 20.0)


class TestProfileMath(unittest.TestCase):
    def test_aov_subtracts_refunds(self) -> None:
        e = cl.CustomerLTV()
        e.observe("c", order_value=100.0)
        e.observe("c", order_value=100.0, refund_value=50.0)
        prof = e.profile("c")
        # AOV = (200 - 50) / 2 = 75
        self.assertAlmostEqual(prof.aov, 75.0)

    def test_first_last_ts_tracked(self) -> None:
        e = cl.CustomerLTV()
        e.observe("c", order_value=10, ts=1000.0)
        e.observe("c", order_value=10, ts=2000.0)
        e.observe("c", order_value=10, ts=500.0)   # back-dated
        prof = e.profile("c")
        self.assertEqual(prof.first_ts, 500.0)
        self.assertEqual(prof.last_ts, 2000.0)


class TestPredict(unittest.TestCase):
    def test_unknown_customer_none(self) -> None:
        e = cl.CustomerLTV()
        self.assertIsNone(e.predict("nobody"))

    def test_predict_positive_for_active_customer(self) -> None:
        e = cl.CustomerLTV()
        # Recent orders → low recency_days → contributes to active cohort
        now = time.time()
        for i in range(5):
            e.observe(
                "c", order_value=20.0,
                ts=now - i * 86_400,  # one per day
            )
        est = e.predict("c", horizon_weeks=12)
        self.assertGreater(est.expected_value, 0.0)
        self.assertEqual(est.horizon_weeks, 12)

    def test_invalid_horizon_raises(self) -> None:
        e = cl.CustomerLTV()
        e.observe("c", order_value=10)
        with self.assertRaises(ValueError):
            e.predict("c", horizon_weeks=0)


class TestChurnHazard(unittest.TestCase):
    def test_hazard_clamped(self) -> None:
        e = cl.CustomerLTV(churn_silent_weeks=8.0)
        # All customers very recent → hazard floor 0.01
        for cid in ("a", "b", "c"):
            e.observe(cid, order_value=10)
        h = e._churn_hazard()
        self.assertGreaterEqual(h, 0.01)
        self.assertLessEqual(h, 0.5)

    def test_hazard_responds_to_dormant_population(self) -> None:
        e = cl.CustomerLTV(churn_silent_weeks=4.0)
        old_ts = time.time() - 100 * 86_400  # ~14 weeks ago
        # Mostly dormant population
        for cid in ("a", "b", "c"):
            e.observe(cid, order_value=10, ts=old_ts)
        e.observe("d", order_value=10)   # one fresh
        # Hazard should sit above the floor.
        self.assertGreater(e._churn_hazard(), 0.5 - 1e-9)


class TestSegmentSummary(unittest.TestCase):
    def test_segments_sorted_by_ltv_desc(self) -> None:
        e = cl.CustomerLTV()
        now = time.time()
        # Audio: high AOV
        for cid in ("a1", "a2"):
            for i in range(3):
                e.observe(
                    cid, order_value=100.0,
                    ts=now - i * 86_400,
                    cohort_keys={"niche": "audio"},
                )
        # Fashion: low AOV
        for cid in ("f1", "f2"):
            for i in range(3):
                e.observe(
                    cid, order_value=10.0,
                    ts=now - i * 86_400,
                    cohort_keys={"niche": "fashion"},
                )
        report = e.segment_summary("niche")
        self.assertEqual(report[0]["cohort_value"], "audio")
        self.assertEqual(report[1]["cohort_value"], "fashion")

    def test_unknown_cohort_key_groups_under_unknown(self) -> None:
        e = cl.CustomerLTV()
        e.observe("c1", order_value=10)
        report = e.segment_summary("source")
        # cohort_keys missing → bucket "(unknown)"
        self.assertEqual(report[0]["cohort_value"], "(unknown)")


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "l.db"
        first = cl.CustomerLTV(db_path=path)
        first.observe(
            "c1", order_value=20.0,
            cohort_keys={"src": "fb"},
        )
        first.close()
        second = cl.CustomerLTV(db_path=path)
        prof = second.profile("c1")
        self.assertIsNotNone(prof)
        self.assertEqual(prof.cohort_keys.get("src"), "fb")
        second.close()
        tmp.cleanup()


class TestStatsAndReset(unittest.TestCase):
    def test_stats(self) -> None:
        e = cl.CustomerLTV()
        e.observe("c", order_value=10)
        s = e.stats()
        self.assertEqual(s["customers"], 1)
        self.assertEqual(s["orders"], 1)

    def test_reset_single(self) -> None:
        e = cl.CustomerLTV()
        e.observe("a", order_value=10)
        e.observe("b", order_value=10)
        n = e.reset("a")
        self.assertEqual(n, 1)
        self.assertEqual(e.stats()["customers"], 1)

    def test_reset_all(self) -> None:
        e = cl.CustomerLTV()
        e.observe("a", order_value=10)
        e.observe("b", order_value=10)
        n = e.reset()
        self.assertEqual(n, 2)
        self.assertEqual(e.stats()["customers"], 0)


class TestDict(unittest.TestCase):
    def test_profile_serialises(self) -> None:
        e = cl.CustomerLTV()
        e.observe("c", order_value=10)
        d = e.profile("c").as_dict()
        self.assertIn("aov", d)
        self.assertIn("frequency_per_week", d)

    def test_estimate_serialises(self) -> None:
        e = cl.CustomerLTV()
        e.observe("c", order_value=10)
        d = e.predict("c").as_dict()
        self.assertIn("expected_value", d)


if __name__ == "__main__":
    unittest.main()
