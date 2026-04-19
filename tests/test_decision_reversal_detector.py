"""Decision reversal detector tests."""
from __future__ import annotations

import unittest

from core.brain import decision_reversal_detector as drd


class TestConfig(unittest.TestCase):
    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            drd.DecisionReversalDetector(window_seconds=0)

    def test_bad_threshold_raises(self) -> None:
        with self.assertRaises(ValueError):
            drd.DecisionReversalDetector(oscillation_threshold=1)

    def test_bad_history_raises(self) -> None:
        with self.assertRaises(ValueError):
            drd.DecisionReversalDetector(history_size=2)


class TestRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.d = drd.DecisionReversalDetector()

    def test_blank_target_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.d.record(target="", action="launch")

    def test_blank_action_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.d.record(target="c1", action="")

    def test_same_action_no_alert(self) -> None:
        a1 = self.d.record(
            target="c1", action="launch", ts=100.0,
        )
        a2 = self.d.record(
            target="c1", action="launch", ts=200.0,
        )
        self.assertIsNone(a1)
        self.assertIsNone(a2)

    def test_first_flip_is_direct_reversal(self) -> None:
        self.d.record(target="c1", action="launch", ts=100.0)
        alert = self.d.record(
            target="c1", action="kill", ts=200.0,
        )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.kind, "direct")
        self.assertEqual(alert.flip_count, 1)

    def test_outside_window_no_alert(self) -> None:
        d = drd.DecisionReversalDetector(window_seconds=100)
        d.record(target="c1", action="launch", ts=100.0)
        alert = d.record(
            target="c1", action="kill", ts=300.0,
        )
        self.assertIsNone(alert)

    def test_three_flips_oscillation(self) -> None:
        d = drd.DecisionReversalDetector(
            window_seconds=1000, oscillation_threshold=3,
        )
        d.record(target="c1", action="launch", ts=100.0)
        d.record(target="c1", action="kill", ts=200.0)
        d.record(target="c1", action="launch", ts=300.0)
        alert = d.record(
            target="c1", action="kill", ts=400.0,
        )
        self.assertIsNotNone(alert)
        self.assertEqual(alert.kind, "oscillation")
        self.assertGreaterEqual(alert.flip_count, 3)


class TestChurnRate(unittest.TestCase):
    def test_no_history(self) -> None:
        d = drd.DecisionReversalDetector()
        self.assertEqual(d.churn_rate("none"), 0.0)

    def test_all_same(self) -> None:
        d = drd.DecisionReversalDetector()
        for i in range(5):
            d.record(
                target="c", action="launch", ts=100.0 + i,
            )
        self.assertEqual(d.churn_rate("c"), 0.0)

    def test_all_flips(self) -> None:
        d = drd.DecisionReversalDetector()
        for i in range(4):
            action = "launch" if i % 2 == 0 else "kill"
            d.record(target="c", action=action, ts=100.0 + i)
        self.assertEqual(d.churn_rate("c"), 1.0)


class TestHistory(unittest.TestCase):
    def test_history_ordered(self) -> None:
        d = drd.DecisionReversalDetector()
        d.record(target="c", action="a", ts=1.0)
        d.record(target="c", action="b", ts=2.0)
        h = d.history("c")
        self.assertEqual([r.action for r in h], ["a", "b"])

    def test_history_bounded(self) -> None:
        d = drd.DecisionReversalDetector(history_size=3)
        for i in range(10):
            d.record(
                target="c", action=str(i), ts=float(i),
            )
        self.assertEqual(len(d.history("c")), 3)


class TestAlerts(unittest.TestCase):
    def test_alerts_limit(self) -> None:
        d = drd.DecisionReversalDetector()
        for i in range(5):
            action = "launch" if i % 2 == 0 else "kill"
            d.record(
                target="c", action=action, ts=100.0 + i * 10,
            )
        self.assertGreater(len(d.alerts()), 0)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        d = drd.DecisionReversalDetector()
        d.record(target="c", action="a")
        s = d.stats()
        self.assertEqual(s["tracked_targets"], 1)
        self.assertIn("window_seconds", s)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        d = drd.DecisionReversalDetector()
        d.record(target="c", action="a", ts=1.0)
        d.record(target="c", action="b", ts=2.0)
        n = d.reset()
        self.assertGreater(n, 0)


class TestDict(unittest.TestCase):
    def test_record_serialises(self) -> None:
        r = drd.DecisionRecord(
            target="c", action="a", ts=1.0,
        )
        d = r.as_dict()
        self.assertEqual(d["action"], "a")

    def test_alert_serialises(self) -> None:
        d = drd.DecisionReversalDetector()
        d.record(target="c", action="launch", ts=1.0)
        alert = d.record(
            target="c", action="kill", ts=2.0,
        )
        out = alert.as_dict()
        self.assertEqual(out["kind"], "direct")


if __name__ == "__main__":
    unittest.main()
