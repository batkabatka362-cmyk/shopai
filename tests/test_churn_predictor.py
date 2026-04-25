"""Churn predictor tests."""
from __future__ import annotations

import time
import unittest

from core.brain import churn_predictor as cp


def _cust(
    cid, last_days_ago=10, first_days_ago=100,
    orders=3, revenue=150.0, now=None,
):
    now = now or time.time()
    return cp.CustomerRecord(
        customer_id=cid,
        last_order_ts=now - last_days_ago * 86_400,
        order_count=orders,
        total_revenue=revenue,
        first_order_ts=now - first_days_ago * 86_400,
    )


class TestRecordMath(unittest.TestCase):
    def test_recency_days(self) -> None:
        r = _cust("x", last_days_ago=7)
        self.assertAlmostEqual(r.recency_days(), 7, places=0)

    def test_avg_gap_days(self) -> None:
        r = _cust("x", first_days_ago=90, orders=4)
        self.assertAlmostEqual(r.avg_gap_days(), 30, places=0)

    def test_avg_gap_single_order(self) -> None:
        r = _cust("x", orders=1)
        self.assertEqual(r.avg_gap_days(), 0.0)


class TestScoreCohort(unittest.TestCase):
    def test_empty_cohort(self) -> None:
        self.assertEqual(cp.score_cohort([]), [])

    def test_top_priority_is_high_value_stale(self) -> None:
        now = time.time()
        records = [
            _cust("stale_rich",
                   last_days_ago=180, first_days_ago=365,
                   orders=10, revenue=5000, now=now),
            _cust("active_casual",
                   last_days_ago=5, first_days_ago=60,
                   orders=2, revenue=60, now=now),
            _cust("stale_casual",
                   last_days_ago=200, first_days_ago=300,
                   orders=2, revenue=40, now=now),
        ]
        scored = cp.score_cohort(records, now_ts=now)
        self.assertEqual(scored[0].customer_id, "stale_rich")

    def test_scores_in_1_to_5_range(self) -> None:
        records = [
            _cust(f"c{i}", last_days_ago=i * 5,
                   orders=i + 1, revenue=i * 50 + 10)
            for i in range(5)
        ]
        scored = cp.score_cohort(records)
        for s in scored:
            for v in (s.recency_score, s.frequency_score,
                       s.monetary_score):
                self.assertGreaterEqual(v, 1)
                self.assertLessEqual(v, 5)

    def test_risk_in_0_to_1_range(self) -> None:
        records = [
            _cust("x", last_days_ago=30),
            _cust("y", last_days_ago=300),
        ]
        scored = cp.score_cohort(records)
        for s in scored:
            self.assertGreaterEqual(s.churn_risk, 0.0)
            self.assertLessEqual(s.churn_risk, 1.0)

    def test_stale_higher_risk_than_recent(self) -> None:
        now = time.time()
        recent = _cust("r", last_days_ago=3, orders=4,
                        first_days_ago=90, now=now)
        stale = _cust("s", last_days_ago=300, orders=4,
                       first_days_ago=400, now=now)
        scored = cp.score_cohort([recent, stale], now_ts=now)
        r_map = {s.customer_id: s for s in scored}
        self.assertGreater(
            r_map["s"].churn_risk, r_map["r"].churn_risk,
        )


class TestSurvival(unittest.TestCase):
    def test_survival_monotone_decreasing(self) -> None:
        now = time.time()
        records = [
            _cust(f"c{i}", last_days_ago=i * 10,
                   first_days_ago=100,
                   orders=3, revenue=50, now=now)
            for i in range(5)
        ]
        curve = cp.survival_curve(records, horizon_days=30,
                                    now_ts=now)
        self.assertEqual(curve[0][0], 0)
        for i in range(1, len(curve)):
            self.assertLessEqual(curve[i][1], curve[i - 1][1])

    def test_survival_empty(self) -> None:
        curve = cp.survival_curve([], horizon_days=30)
        self.assertEqual(curve, [(0, 1.0)])

    def test_survival_zero_horizon(self) -> None:
        records = [_cust("c")]
        self.assertEqual(
            cp.survival_curve(records, horizon_days=0),
            [(0, 1.0)],
        )


class TestSaveTarget(unittest.TestCase):
    def test_filter_by_risk_threshold(self) -> None:
        now = time.time()
        records = [
            _cust("safe", last_days_ago=2, orders=4,
                   first_days_ago=90, now=now),
            _cust("at_risk", last_days_ago=300, orders=4,
                   first_days_ago=400, revenue=1000, now=now),
        ]
        targets = cp.target_for_save_campaign(
            records, min_churn_risk=0.5, now_ts=now,
        )
        ids = [t.customer_id for t in targets]
        self.assertIn("at_risk", ids)
        self.assertNotIn("safe", ids)

    def test_top_k_truncates(self) -> None:
        records = [
            _cust(f"c{i}", last_days_ago=200, orders=4,
                   first_days_ago=400, revenue=1000 - i)
            for i in range(20)
        ]
        targets = cp.target_for_save_campaign(
            records, top_k=5, min_churn_risk=0.0,
        )
        self.assertLessEqual(len(targets), 5)


if __name__ == "__main__":
    unittest.main()
