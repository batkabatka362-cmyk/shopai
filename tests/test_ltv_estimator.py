"""LTV estimator tests."""
from __future__ import annotations

import time
import unittest

from core.brain import ltv_estimator as lt


def _record(
    cust_id="c1", days_ago_first=100, days_ago_last=10,
    order_count=5, total_revenue=500.0, now=None,
):
    now = now or time.time()
    return lt.CustomerRecord(
        customer_id=cust_id,
        first_order_ts=now - days_ago_first * 86_400,
        last_order_ts=now - days_ago_last * 86_400,
        order_count=order_count,
        total_revenue=total_revenue,
    )


class TestRecord(unittest.TestCase):
    def test_avg_order_value(self) -> None:
        r = _record(order_count=4, total_revenue=200)
        self.assertAlmostEqual(r.avg_order_value, 50.0)

    def test_tenure_days(self) -> None:
        r = _record(days_ago_first=90, days_ago_last=0)
        self.assertAlmostEqual(r.tenure_days, 90, places=0)

    def test_inter_gap_single_order(self) -> None:
        r = _record(order_count=1)
        self.assertEqual(r.inter_order_gap_days, 0.0)


class TestFitCohort(unittest.TestCase):
    def test_empty_cohort(self) -> None:
        c = lt.fit_cohort([])
        self.assertEqual(c.n_customers, 0)

    def test_mixed_cohort(self) -> None:
        records = [
            _record(order_count=1, total_revenue=30),
            _record(order_count=4, total_revenue=200),
            _record(order_count=2, total_revenue=60),
        ]
        c = lt.fit_cohort(records)
        self.assertEqual(c.n_customers, 3)
        # repeat_rate: 2 of 3 customers have ≥2 orders
        self.assertAlmostEqual(c.avg_repeat_rate, 2 / 3)
        self.assertGreater(c.avg_inter_gap_days, 0)


class TestAliveProb(unittest.TestCase):
    def test_recent_customer_alive(self) -> None:
        est = lt.LTVEstimator()
        now = time.time()
        r = _record(days_ago_last=1, now=now)
        self.assertGreater(est.alive_prob(r, now_ts=now), 0.8)

    def test_long_absent_customer_dead(self) -> None:
        est = lt.LTVEstimator()
        now = time.time()
        r = _record(
            days_ago_first=200, days_ago_last=100,
            order_count=3, now=now,
        )
        self.assertLess(est.alive_prob(r, now_ts=now), 0.3)

    def test_alive_clamped_at_one(self) -> None:
        est = lt.LTVEstimator()
        now = time.time()
        r = _record(days_ago_last=0, now=now)
        self.assertLessEqual(est.alive_prob(r, now_ts=now), 1.0)


class TestExpectedOrders(unittest.TestCase):
    def test_zero_horizon(self) -> None:
        est = lt.LTVEstimator()
        r = _record()
        self.assertEqual(est.expected_orders(r, 0), 0.0)

    def test_single_order_uses_cohort(self) -> None:
        est = lt.LTVEstimator(cohort=lt.CohortStats(
            n_customers=100,
            avg_first_order_value=30,
            avg_order_value=30,
            avg_repeat_rate=0.5,
            avg_inter_gap_days=30,
        ))
        r = _record(order_count=1, total_revenue=30)
        est_orders = est.expected_orders(r, 60)
        # 0.5 × 60 / 30 = 1
        self.assertAlmostEqual(est_orders, 1.0, places=1)

    def test_multi_order_uses_own_rate(self) -> None:
        est = lt.LTVEstimator()
        now = time.time()
        r = _record(
            days_ago_first=100, days_ago_last=10,
            order_count=5, now=now,
        )
        orders = est.expected_orders(r, 90, now_ts=now)
        self.assertGreater(orders, 0)


class TestLTV(unittest.TestCase):
    def test_ltv_positive_for_recent_buyer(self) -> None:
        est = lt.LTVEstimator()
        now = time.time()
        r = _record(
            days_ago_last=5, order_count=5, total_revenue=250, now=now,
        )
        ltv = est.ltv(r, horizon_days=180, now_ts=now)
        self.assertGreater(ltv.predicted_revenue, 0)
        self.assertGreater(ltv.alive_prob, 0.8)

    def test_ltv_low_for_absent(self) -> None:
        est = lt.LTVEstimator()
        now = time.time()
        recent = _record(days_ago_last=5, now=now)
        absent = _record(
            days_ago_first=500, days_ago_last=300,
            order_count=3, total_revenue=90, now=now,
        )
        ltv_recent = est.ltv(recent, now_ts=now)
        ltv_absent = est.ltv(absent, now_ts=now)
        self.assertGreater(
            ltv_recent.predicted_revenue,
            ltv_absent.predicted_revenue,
        )

    def test_ltv_fit_updates_cohort(self) -> None:
        est = lt.LTVEstimator()
        records = [
            _record(order_count=2, total_revenue=80),
            _record(order_count=3, total_revenue=150),
        ]
        c = est.fit(records)
        self.assertEqual(c.n_customers, 2)
        self.assertEqual(est.cohort().n_customers, 2)


if __name__ == "__main__":
    unittest.main()
