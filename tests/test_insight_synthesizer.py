"""Insight synthesizer tests."""
from __future__ import annotations

import unittest

from core.brain import insight_synthesizer as ins


class TestSynthesise(unittest.TestCase):
    def setUp(self) -> None:
        self.s = ins.InsightSynthesizer()

    def test_empty_inputs_empty_output(self) -> None:
        self.assertEqual(self.s.synthesise(), [])

    def test_calibration_insight(self) -> None:
        report = {
            "calibration_error": 0.3,
            "overconfidence_score": 0.25,
            "n_total": 20,
        }
        produced = self.s.synthesise(
            calibration_report=report,
        )
        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0].kind, "calibration")

    def test_calibration_below_threshold_skipped(self) -> None:
        report = {
            "calibration_error": 0.05,
            "overconfidence_score": 0.02,
            "n_total": 20,
        }
        self.assertEqual(
            self.s.synthesise(calibration_report=report), [],
        )

    def test_drift_insight_per_alert(self) -> None:
        alerts = [
            {
                "predictor_id": "p1",
                "suggestion": "shift intercept by 0.5",
            },
            {
                "predictor_id": "p2",
                "suggestion": "shift intercept by -0.2",
            },
        ]
        produced = self.s.synthesise(drift_alerts=alerts)
        self.assertEqual(len(produced), 2)

    def test_assumption_violation_insight(self) -> None:
        stats = {"total": 10, "violation_rate": 0.7}
        produced = self.s.synthesise(assumption_stats=stats)
        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0].severity, "critical")

    def test_assumption_low_violation_skipped(self) -> None:
        stats = {"total": 10, "violation_rate": 0.1}
        self.assertEqual(
            self.s.synthesise(assumption_stats=stats), [],
        )

    def test_funnel_insight(self) -> None:
        snap = {
            "biggest_leak": ["impression", "click"],
            "biggest_leak_diagnosis": "low CTR — creative fatigue",
            "overall_conversion": 0.001,
        }
        produced = self.s.synthesise(funnel_snapshot=snap)
        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0].severity, "warning")

    def test_pre_breach_critical(self) -> None:
        alerts = [{
            "kpi": "roas", "severity": "critical",
            "direction": "below",
            "projected_breach_s": 60, "confidence": 0.8,
        }]
        produced = self.s.synthesise(pre_breach_alerts=alerts)
        self.assertEqual(len(produced), 1)
        self.assertEqual(produced[0].severity, "critical")

    def test_pre_breach_none_skipped(self) -> None:
        alerts = [{
            "kpi": "roas", "severity": "none",
            "direction": "below",
        }]
        self.assertEqual(
            self.s.synthesise(pre_breach_alerts=alerts), [],
        )

    def test_multiple_sources(self) -> None:
        produced = self.s.synthesise(
            calibration_report={
                "calibration_error": 0.3,
                "overconfidence_score": 0.2,
                "n_total": 10,
            },
            assumption_stats={
                "total": 10, "violation_rate": 0.5,
            },
        )
        self.assertEqual(len(produced), 2)

    def test_prioritised_critical_first(self) -> None:
        produced = self.s.synthesise(
            calibration_report={
                "calibration_error": 0.5,   # critical
                "overconfidence_score": 0.4,
                "n_total": 10,
            },
            funnel_snapshot={
                "biggest_leak": ["checkout", "purchase"],
                "biggest_leak_diagnosis": "x",
                "overall_conversion": 0.05,
            },
        )
        self.assertEqual(produced[0].severity, "critical")


class TestLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.s = ins.InsightSynthesizer()
        produced = self.s.synthesise(
            calibration_report={
                "calibration_error": 0.5,
                "overconfidence_score": 0.4,
                "n_total": 10,
            },
        )
        self.i = produced[0]

    def test_pin(self) -> None:
        r = self.s.pin(self.i.id)
        self.assertTrue(r.pinned)

    def test_dismiss(self) -> None:
        r = self.s.dismiss(self.i.id)
        self.assertTrue(r.dismissed)

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.s.pin("nope")
        with self.assertRaises(ValueError):
            self.s.dismiss("nope")


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.s = ins.InsightSynthesizer()
        self.produced = self.s.synthesise(
            calibration_report={
                "calibration_error": 0.3,
                "overconfidence_score": 0.2,
                "n_total": 10,
            },
            assumption_stats={
                "total": 10, "violation_rate": 0.7,
            },
        )

    def test_active_excludes_dismissed(self) -> None:
        a_before = len(self.s.active())
        self.s.dismiss(self.produced[0].id)
        self.assertEqual(len(self.s.active()), a_before - 1)

    def test_pinned_first(self) -> None:
        a = self.produced[0]
        self.s.pin(a.id)
        active = self.s.active()
        self.assertEqual(active[0].id, a.id)

    def test_pinned_query(self) -> None:
        self.s.pin(self.produced[0].id)
        self.assertEqual(len(self.s.pinned()), 1)

    def test_limit(self) -> None:
        active = self.s.active(limit=1)
        self.assertEqual(len(active), 1)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        s = ins.InsightSynthesizer()
        s.synthesise(
            calibration_report={
                "calibration_error": 0.3,
                "overconfidence_score": 0.2,
                "n_total": 10,
            },
        )
        st = s.stats()
        self.assertEqual(st["active"], 1)
        self.assertIn("warning", st["by_severity"])


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        s = ins.InsightSynthesizer()
        s.synthesise(
            calibration_report={
                "calibration_error": 0.3,
                "overconfidence_score": 0.2,
                "n_total": 10,
            },
        )
        self.assertEqual(s.reset(), 1)


class TestDict(unittest.TestCase):
    def test_insight_serialises(self) -> None:
        s = ins.InsightSynthesizer()
        p = s.synthesise(
            calibration_report={
                "calibration_error": 0.3,
                "overconfidence_score": 0.2,
                "n_total": 10,
            },
        )
        d = p[0].as_dict()
        self.assertIn("statement", d)
        self.assertIn("severity", d)


if __name__ == "__main__":
    unittest.main()
