"""Tests for core.planning.quarterly_planner — L4 long-horizon."""
from __future__ import annotations

import time
import unittest

from core.planning.quarterly_planner import (
    Milestone,
    ProgressReport,
    QuarterlyGoal,
    QuarterlyPlan,
    build_quarterly_plan,
    check_in,
)


_NOW = 1_700_000_000.0
_WEEK = 7 * 24 * 3600.0
_QUARTER = 13 * _WEEK


def _goal(**overrides):
    kw = dict(
        revenue_target_monthly_usd=5_000.0,
        deadline_ts=_NOW + _QUARTER,
        start_ts=_NOW,
        sku_target=20,
        roas_target=1.8,
        ramp_curve="linear",
        niche="pet",
    )
    kw.update(overrides)
    return QuarterlyGoal(**kw)


class TestGoalValidation(unittest.TestCase):
    def test_negative_revenue_raises(self):
        with self.assertRaises(ValueError):
            _goal(revenue_target_monthly_usd=-1)

    def test_zero_sku_raises(self):
        with self.assertRaises(ValueError):
            _goal(sku_target=0)

    def test_zero_roas_raises(self):
        with self.assertRaises(ValueError):
            _goal(roas_target=0)

    def test_deadline_before_start_raises(self):
        with self.assertRaises(ValueError):
            _goal(
                start_ts=_NOW,
                deadline_ts=_NOW - 1,
            )

    def test_invalid_ramp_raises(self):
        with self.assertRaises(ValueError):
            _goal(ramp_curve="exponential")


class TestBuilder(unittest.TestCase):
    def test_13_week_plan_has_13_milestones(self):
        plan = build_quarterly_plan(_goal())
        self.assertEqual(len(plan.milestones), 13)

    def test_final_milestone_hits_target(self):
        plan = build_quarterly_plan(_goal())
        final = plan.milestones[-1]
        # ~3.03 months × $5000/mo ≈ $15,167 cumulative at end
        self.assertAlmostEqual(
            final.cumulative_revenue_usd / 1000.0,
            15.0, delta=0.5,
        )
        self.assertEqual(
            final.skus_live_target, 20,
        )

    def test_linear_ramp_is_monotone(self):
        plan = build_quarterly_plan(_goal())
        revenues = [
            m.cumulative_revenue_usd
            for m in plan.milestones
        ]
        for a, b in zip(revenues, revenues[1:]):
            self.assertLessEqual(a, b)

    def test_front_loaded_hits_target_faster_early(self):
        plan_linear = build_quarterly_plan(
            _goal(ramp_curve="linear"),
        )
        plan_front = build_quarterly_plan(
            _goal(ramp_curve="front_loaded"),
        )
        # Midpoint: front_loaded should have higher
        # cumulative than linear
        self.assertGreater(
            plan_front.milestones[6].cumulative_revenue_usd,
            plan_linear.milestones[6]
            .cumulative_revenue_usd,
        )

    def test_back_loaded_is_slower_early(self):
        plan_linear = build_quarterly_plan(
            _goal(ramp_curve="linear"),
        )
        plan_back = build_quarterly_plan(
            _goal(ramp_curve="back_loaded"),
        )
        self.assertLess(
            plan_back.milestones[6].cumulative_revenue_usd,
            plan_linear.milestones[6]
            .cumulative_revenue_usd,
        )

    def test_zero_cadence_raises(self):
        with self.assertRaises(ValueError):
            build_quarterly_plan(_goal(), cadence_s=0)


class TestActiveMilestone(unittest.TestCase):
    def test_before_start_no_active(self):
        plan = build_quarterly_plan(_goal())
        self.assertIsNone(
            plan.active_milestone(now_ts=_NOW - 1),
        )

    def test_week_1_in_progress(self):
        plan = build_quarterly_plan(_goal())
        # Half a week in — no milestone complete yet
        self.assertIsNone(
            plan.active_milestone(
                now_ts=_NOW + _WEEK * 0.5,
            ),
        )

    def test_week_2_active_is_week_1(self):
        plan = build_quarterly_plan(_goal())
        active = plan.active_milestone(
            now_ts=_NOW + _WEEK * 1.5,
        )
        self.assertIsNotNone(active)
        self.assertEqual(active.week_index, 1)

    def test_next_milestone(self):
        plan = build_quarterly_plan(_goal())
        nxt = plan.next_milestone(
            now_ts=_NOW + _WEEK * 1.5,
        )
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.week_index, 2)


class TestCheckIn(unittest.TestCase):
    def setUp(self):
        self.plan = build_quarterly_plan(_goal())

    def test_before_start_is_on_track(self):
        report = check_in(
            self.plan,
            current_revenue_usd=0.0,
            now_ts=_NOW - 1,
        )
        self.assertEqual(report.verdict, "on_track")
        self.assertIsNone(report.current_milestone)

    def test_on_track_verdict(self):
        now = _NOW + _WEEK * 2.5   # active = week 2
        target = self.plan.milestones[1].cumulative_revenue_usd
        report = check_in(
            self.plan,
            current_revenue_usd=target,
            current_skus_live=20,
            now_ts=now,
        )
        self.assertEqual(report.verdict, "on_track")

    def test_ahead_verdict(self):
        now = _NOW + _WEEK * 2.5
        target = self.plan.milestones[1].cumulative_revenue_usd
        report = check_in(
            self.plan,
            current_revenue_usd=target * 2.0,
            current_skus_live=20,
            now_ts=now,
        )
        self.assertEqual(report.verdict, "ahead")

    def test_behind_verdict(self):
        now = _NOW + _WEEK * 2.5
        target = self.plan.milestones[1].cumulative_revenue_usd
        report = check_in(
            self.plan,
            current_revenue_usd=target * 0.85,
            current_skus_live=20,
            now_ts=now,
        )
        self.assertEqual(report.verdict, "behind")

    def test_at_risk_on_shortfall(self):
        now = _NOW + _WEEK * 2.5
        report = check_in(
            self.plan,
            current_revenue_usd=0.0,
            current_skus_live=0,
            now_ts=now,
        )
        self.assertEqual(report.verdict, "at_risk")

    def test_at_risk_multiple_missed(self):
        # Isolate the "≥ N missed milestones" path: set a huge
        # shortfall threshold so only missed-count drives the
        # verdict. At week 4.5 four milestones are due; revenue
        # below target2 misses weeks 2+3+4 → 3 misses.
        now = _NOW + _WEEK * 4.5
        target2 = self.plan.milestones[1].cumulative_revenue_usd
        report = check_in(
            self.plan,
            current_revenue_usd=target2 * 0.99,
            current_skus_live=20,
            now_ts=now,
            at_risk_shortfall=0.99,   # disable shortfall path
            at_risk_missed=2,
        )
        self.assertEqual(report.verdict, "at_risk")
        self.assertGreaterEqual(report.missed_milestones, 2)

    def test_on_track_demoted_when_skus_half_target(self):
        now = _NOW + _WEEK * 6.5
        target = self.plan.milestones[5].cumulative_revenue_usd
        report = check_in(
            self.plan,
            current_revenue_usd=target,
            current_skus_live=1,   # way below half
            now_ts=now,
        )
        self.assertEqual(report.verdict, "behind")
        self.assertIn("SKUs live", report.reason)

    def test_recommendation_populated(self):
        now = _NOW + _WEEK * 2.5
        target = self.plan.milestones[1].cumulative_revenue_usd
        report = check_in(
            self.plan,
            current_revenue_usd=target * 0.5,
            now_ts=now,
        )
        self.assertTrue(report.recommendation)


class TestDict(unittest.TestCase):
    def test_plan_dict(self):
        plan = build_quarterly_plan(_goal())
        d = plan.as_dict()
        self.assertIn("milestones", d)
        self.assertEqual(len(d["milestones"]), 13)

    def test_report_dict(self):
        plan = build_quarterly_plan(_goal())
        report = check_in(
            plan,
            current_revenue_usd=100.0,
            now_ts=_NOW + _WEEK * 2.5,
        )
        d = report.as_dict()
        self.assertIn("verdict", d)
        self.assertIn("recommendation", d)


if __name__ == "__main__":
    unittest.main()
