"""Unit tests for core.autonomous.launch_evaluator.

Verifies the bucketer produces the right kill / scale / monitor
verdict for a range of ROAS + data-horizon combinations without
touching the actual MemoryIntelligence DB.
"""
from __future__ import annotations

import time
import unittest

from core.autonomous.launch_evaluator import (
    LaunchStats, _bucket,
)


class TestBucketer(unittest.TestCase):
    def _make(self, **kw) -> LaunchStats:
        defaults = dict(
            launch_id="l1", registered_at=time.time() - 4 * 86400,
            kill_roas=1.5, scale_roas=2.0, kill_after_days=3,
            ad_budget_day=20.0,
        )
        defaults.update(kw)
        s = LaunchStats(**defaults)
        # Simulate `_attach_orders` having run
        s.days_live = 4.0
        s.estimated_spend = s.ad_budget_day * s.days_live
        if s.estimated_spend and s.revenue_usd:
            s.estimated_roas = s.revenue_usd / s.estimated_spend
        if s.order_count:
            s.aov = s.revenue_usd / s.order_count
        return s

    def test_insufficient_data_before_horizon(self) -> None:
        s = self._make()
        s.days_live = 1.0
        s.registered_at = time.time() - 86400
        report = _bucket({"l1": s})
        self.assertEqual(len(report.monitor_recommendations), 1)
        self.assertEqual(report.monitor_recommendations[0].verdict, "waiting_for_data")
        self.assertEqual(report.launches_evaluated, 0)

    def test_kill_when_roas_below_threshold(self) -> None:
        s = self._make(revenue_usd=40.0)   # spend = $80, ROAS 0.5
        report = _bucket({"l1": s})
        self.assertEqual(len(report.kill_recommendations), 1)
        self.assertEqual(report.kill_recommendations[0].verdict, "kill")
        self.assertIn("< kill threshold", report.kill_recommendations[0].reason)

    def test_scale_when_roas_hits_target(self) -> None:
        s = self._make(revenue_usd=200.0, order_count=6)  # spend $80, ROAS 2.5
        report = _bucket({"l1": s})
        self.assertEqual(len(report.scale_recommendations), 1)
        self.assertEqual(report.scale_recommendations[0].verdict, "scale")

    def test_hold_in_safe_zone(self) -> None:
        s = self._make(revenue_usd=140.0, order_count=4)  # spend $80, ROAS 1.75
        report = _bucket({"l1": s})
        self.assertEqual(len(report.monitor_recommendations), 1)
        self.assertEqual(report.monitor_recommendations[0].verdict, "hold")

    def test_no_budget_means_monitor_only(self) -> None:
        s = self._make(ad_budget_day=0.0, revenue_usd=100.0)
        s.estimated_spend = 0  # simulate recompute after zero budget
        s.estimated_roas = 0
        report = _bucket({"l1": s})
        self.assertEqual(len(report.monitor_recommendations), 1)
        self.assertEqual(report.monitor_recommendations[0].verdict, "monitor")
        self.assertIn("no ad_budget_day", report.monitor_recommendations[0].reason)

    def test_all_launches_counted(self) -> None:
        a = self._make(revenue_usd=10.0, launch_id="a")      # kill
        b = self._make(revenue_usd=300.0, order_count=10, launch_id="b")  # scale
        report = _bucket({"a": a, "b": b})
        self.assertEqual(report.launches_tracked, 2)
        self.assertEqual(report.launches_evaluated, 2)


if __name__ == "__main__":
    unittest.main()
