"""Predictive alerter tests."""
from __future__ import annotations

import unittest

from core.brain import predictive_alerter as pa


class TestConfig(unittest.TestCase):
    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            pa.PredictiveAlerter(window=2)

    def test_bad_min_samples_raises(self) -> None:
        with self.assertRaises(ValueError):
            pa.PredictiveAlerter(min_samples=1)

    def test_horizon_order_raises(self) -> None:
        with self.assertRaises(ValueError):
            pa.PredictiveAlerter(
                warning_horizon_s=60, critical_horizon_s=600,
            )


class TestObserve(unittest.TestCase):
    def test_blank_kpi_raises(self) -> None:
        alerter = pa.PredictiveAlerter()
        with self.assertRaises(ValueError):
            alerter.observe("", 1.0)

    def test_observe_appends(self) -> None:
        alerter = pa.PredictiveAlerter()
        alerter.observe("roas", 1.0, ts=100.0)
        alerter.observe("roas", 1.1, ts=101.0)
        summary = alerter.summary("roas")
        self.assertEqual(summary["samples"], 2)
        self.assertEqual(summary["latest"], 1.1)

    def test_window_bounded(self) -> None:
        alerter = pa.PredictiveAlerter(window=3)
        for i in range(10):
            alerter.observe("k", float(i), ts=float(i))
        summary = alerter.summary("k")
        self.assertEqual(summary["samples"], 3)


class TestEvaluate(unittest.TestCase):
    def setUp(self) -> None:
        self.alerter = pa.PredictiveAlerter(
            window=30, min_samples=5,
            warning_horizon_s=6 * 3600,
            critical_horizon_s=30 * 60,
        )

    def test_bad_direction_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.alerter.evaluate(
                "k", threshold=1.0,
                direction="sideways",  # type: ignore[arg-type]
            )

    def test_cold_start_returns_none_severity(self) -> None:
        self.alerter.observe("k", 1.0, ts=0.0)
        self.alerter.observe("k", 1.1, ts=1.0)
        alert = self.alerter.evaluate(
            "k", threshold=2.0, direction="above", now=2.0,
        )
        self.assertEqual(alert.severity, "none")
        self.assertIsNone(alert.projected_breach_s)
        self.assertIn("need", alert.note)

    def test_no_samples_returns_none(self) -> None:
        alert = self.alerter.evaluate(
            "unknown_kpi", threshold=1.0,
            direction="above", now=0.0,
        )
        self.assertEqual(alert.severity, "none")
        self.assertEqual(alert.n_samples, 0)

    def test_already_above_threshold_is_critical(self) -> None:
        # Constant value that's above threshold
        for i in range(6):
            self.alerter.observe("cpm", 50.0, ts=float(i))
        alert = self.alerter.evaluate(
            "cpm", threshold=30.0, direction="above", now=10.0,
        )
        self.assertEqual(alert.severity, "critical")
        self.assertEqual(alert.projected_breach_s, 0.0)
        self.assertIn("already breaching", alert.note)

    def test_already_below_threshold_is_critical(self) -> None:
        for i in range(6):
            self.alerter.observe("roas", 0.5, ts=float(i))
        alert = self.alerter.evaluate(
            "roas", threshold=1.5, direction="below", now=10.0,
        )
        self.assertEqual(alert.severity, "critical")
        self.assertEqual(alert.projected_breach_s, 0.0)

    def test_zero_slope_no_trajectory(self) -> None:
        # Perfectly flat series below threshold (going above)
        for i in range(6):
            self.alerter.observe("k", 1.0, ts=float(i))
        alert = self.alerter.evaluate(
            "k", threshold=5.0, direction="above", now=10.0,
        )
        self.assertEqual(alert.severity, "none")
        self.assertIsNone(alert.projected_breach_s)
        self.assertIn("zero slope", alert.note)

    def test_trajectory_away_from_threshold(self) -> None:
        # Values decreasing, but threshold is above
        for i in range(6):
            self.alerter.observe("k", 5.0 - i * 0.1, ts=float(i))
        alert = self.alerter.evaluate(
            "k", threshold=10.0, direction="above", now=10.0,
        )
        self.assertEqual(alert.severity, "none")
        self.assertIsNone(alert.projected_breach_s)
        self.assertIn("heading away", alert.note)

    def test_critical_soon(self) -> None:
        # Rising toward threshold; breach soon
        # y = 1 + 0.1*t ; at t=100 y=11. With threshold=11.5, breach at t=105
        for i in range(6):
            self.alerter.observe("k", 1.0 + 0.1 * i, ts=float(i))
        # Now=100, current value at t=5 is 1.5; projecting forward:
        # breach at t=105 → 5 seconds
        alert = self.alerter.evaluate(
            "k", threshold=1.6, direction="above", now=5.5,
        )
        self.assertEqual(alert.severity, "critical")
        self.assertIsNotNone(alert.projected_breach_s)
        self.assertLessEqual(alert.projected_breach_s, 30 * 60)

    def test_warning_horizon(self) -> None:
        # Slope 0.001/s, start at 1.0, threshold 2.0 → 1000s = ~16 min
        # Wait, 1000s < critical_horizon (1800s) — let's use 3000s
        # slope = 0.0005/s, threshold 2.0 → 2000s to cross.
        # That's 33min = critical. Need 3000s.
        # Use slope 0.0001/s → (2-1)/0.0001 = 10000s ≈ 2.8h → warning
        for i in range(6):
            self.alerter.observe(
                "k", 1.0 + 0.0001 * i, ts=float(i),
            )
        alert = self.alerter.evaluate(
            "k", threshold=2.0, direction="above", now=5.0,
        )
        self.assertEqual(alert.severity, "warning")

    def test_info_horizon(self) -> None:
        # slope 0.00001/s → (2-1)/0.00001 = 100000s ≈ 27h → info
        for i in range(6):
            self.alerter.observe(
                "k", 1.0 + 0.00001 * i, ts=float(i),
            )
        alert = self.alerter.evaluate(
            "k", threshold=2.0, direction="above", now=5.0,
        )
        self.assertEqual(alert.severity, "info")

    def test_past_projection_overdue(self) -> None:
        # The fit says breach already happened but current value not yet
        # crossed (can happen with noise). Build: values straddle,
        # fit line suggests negative breach_ts.
        # Start with values just below threshold, slowly rising.
        # Threshold just above the latest value, with line projecting
        # backward past.
        # y = 2.0 + 0.001*t, at t=0 y=2.0 (above threshold 1.9)
        # but we want current value BELOW and projection past.
        # Easier: already-breaching covers "above" detection on current.
        # For past projection: current value is exactly at threshold,
        # slope is strongly in direction. Skip — the "already breaching"
        # and "past projection" code paths use strict inequalities so
        # current_value == threshold is not-breaching.
        self.alerter.observe("k", 1.89, ts=0.0)
        self.alerter.observe("k", 1.895, ts=1.0)
        self.alerter.observe("k", 1.899, ts=2.0)
        self.alerter.observe("k", 1.8995, ts=3.0)
        self.alerter.observe("k", 1.8999, ts=4.0)
        # Current value 1.8999, threshold 1.9, slope ~ +0.003/s rising.
        # breach_ts = (1.9 - intercept) / slope — should be near t=5
        # If we set now=100, then seconds_to_breach = ~-95 → overdue
        alert = self.alerter.evaluate(
            "k", threshold=1.9, direction="above", now=1000.0,
        )
        # Either critical with overdue note, or already breaching
        self.assertEqual(alert.severity, "critical")


class TestSummary(unittest.TestCase):
    def test_unknown_returns_none(self) -> None:
        a = pa.PredictiveAlerter()
        self.assertIsNone(a.summary("never"))

    def test_summary_fields(self) -> None:
        a = pa.PredictiveAlerter()
        for i, v in enumerate([1.0, 2.0, 3.0]):
            a.observe("k", v, ts=float(i))
        s = a.summary("k")
        self.assertEqual(s["samples"], 3)
        self.assertEqual(s["min"], 1.0)
        self.assertEqual(s["max"], 3.0)
        self.assertEqual(s["latest"], 3.0)


class TestReset(unittest.TestCase):
    def test_reset_specific(self) -> None:
        a = pa.PredictiveAlerter()
        a.observe("a", 1.0)
        a.observe("b", 2.0)
        n = a.reset("a")
        self.assertEqual(n, 1)
        self.assertIsNone(a.summary("a"))
        self.assertIsNotNone(a.summary("b"))

    def test_reset_all(self) -> None:
        a = pa.PredictiveAlerter()
        a.observe("a", 1.0)
        a.observe("b", 2.0)
        n = a.reset()
        self.assertEqual(n, 2)
        self.assertIsNone(a.summary("a"))

    def test_reset_unknown(self) -> None:
        a = pa.PredictiveAlerter()
        self.assertEqual(a.reset("nope"), 0)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        a = pa.PredictiveAlerter(window=10, min_samples=3)
        a.observe("x", 1.0)
        s = a.stats()
        self.assertEqual(s["tracked_kpis"], 1)
        self.assertEqual(s["window"], 10)
        self.assertEqual(s["min_samples"], 3)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        a = pa.PredictiveAlerter()
        for i in range(6):
            a.observe("k", 1.0 + 0.1 * i, ts=float(i))
        alert = a.evaluate(
            "k", threshold=5.0, direction="above", now=5.0,
        )
        d = alert.as_dict()
        self.assertIn("kpi", d)
        self.assertIn("severity", d)
        self.assertIn("slope", d)
        self.assertEqual(d["direction"], "above")


if __name__ == "__main__":
    unittest.main()
