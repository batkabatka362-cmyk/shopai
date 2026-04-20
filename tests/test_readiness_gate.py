"""Readiness gate tests."""
from __future__ import annotations

import unittest

from core.brain import readiness_gate as rg


class TestInput(unittest.TestCase):
    def test_bad_probability_raises(self) -> None:
        with self.assertRaises(ValueError):
            rg.ReadinessInput(
                evidence_probability=2.0,
                evidence_gap=0.1,
                knowledge_freshness=0.5,
            )

    def test_bad_gap_raises(self) -> None:
        with self.assertRaises(ValueError):
            rg.ReadinessInput(
                evidence_probability=0.5,
                evidence_gap=-0.1,
                knowledge_freshness=0.5,
            )

    def test_bad_urgency_raises(self) -> None:
        with self.assertRaises(ValueError):
            rg.ReadinessInput(
                evidence_probability=0.5,
                evidence_gap=0.1,
                knowledge_freshness=0.5,
                urgency=-1,
            )


class TestThresholds(unittest.TestCase):
    def test_bad_threshold_raises(self) -> None:
        with self.assertRaises(ValueError):
            rg.ReadinessThresholds(min_probability=2.0)


class TestCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.g = rg.ReadinessGate()

    def test_go_verdict(self) -> None:
        decision = self.g.check(rg.ReadinessInput(
            evidence_probability=0.9,
            evidence_gap=0.1,
            knowledge_freshness=0.9,
            mood_temperature=0.4,
            urgency=1,
        ))
        self.assertEqual(decision.verdict, "go")
        self.assertEqual(decision.recommended_wait_s, 0.0)

    def test_stand_down_low_probability(self) -> None:
        decision = self.g.check(rg.ReadinessInput(
            evidence_probability=0.1,
            evidence_gap=0.3,
            knowledge_freshness=0.8,
        ))
        self.assertEqual(decision.verdict, "stand_down")

    def test_warm_up_stale_knowledge(self) -> None:
        decision = self.g.check(rg.ReadinessInput(
            evidence_probability=0.7,
            evidence_gap=0.2,
            knowledge_freshness=0.1,
        ))
        self.assertEqual(decision.verdict, "warm_up")
        self.assertGreater(decision.recommended_wait_s, 0)

    def test_gather_wide_gap(self) -> None:
        decision = self.g.check(rg.ReadinessInput(
            evidence_probability=0.7,
            evidence_gap=0.9,
            knowledge_freshness=0.8,
        ))
        self.assertEqual(decision.verdict, "gather")

    def test_urgency_relaxes_thresholds(self) -> None:
        inp = rg.ReadinessInput(
            evidence_probability=0.45,
            evidence_gap=0.4,
            knowledge_freshness=0.55,
            urgency=0,
        )
        no_urgency = self.g.check(inp)
        urgent = self.g.check(rg.ReadinessInput(
            evidence_probability=0.45,
            evidence_gap=0.4,
            knowledge_freshness=0.55,
            urgency=3,
        ))
        # urgent may flip from "gather" to "go"
        self.assertNotEqual(
            no_urgency.verdict, urgent.verdict,
        )

    def test_score_in_0_1(self) -> None:
        d = self.g.check(rg.ReadinessInput(
            evidence_probability=1.0,
            evidence_gap=0.0,
            knowledge_freshness=1.0,
            mood_temperature=1.0,
        ))
        self.assertGreaterEqual(d.score, 0.0)
        self.assertLessEqual(d.score, 1.0)


class TestThresholdOverride(unittest.TestCase):
    def test_set_thresholds(self) -> None:
        g = rg.ReadinessGate()
        g.set_thresholds(rg.ReadinessThresholds(
            min_probability=0.8,
            max_gap=0.1,
            min_freshness=0.8,
        ))
        decision = g.check(rg.ReadinessInput(
            evidence_probability=0.6,
            evidence_gap=0.2,
            knowledge_freshness=0.7,
        ))
        # Stricter thresholds → not "go"
        self.assertNotEqual(decision.verdict, "go")


class TestHistory(unittest.TestCase):
    def test_recent(self) -> None:
        g = rg.ReadinessGate()
        for _ in range(3):
            g.check(rg.ReadinessInput(
                evidence_probability=0.5,
                evidence_gap=0.3,
                knowledge_freshness=0.6,
            ))
        self.assertEqual(len(g.recent(limit=2)), 2)

    def test_stats(self) -> None:
        g = rg.ReadinessGate()
        g.check(rg.ReadinessInput(
            evidence_probability=0.9,
            evidence_gap=0.1,
            knowledge_freshness=0.9,
        ))
        s = g.stats()
        self.assertEqual(s["total"], 1)
        self.assertIn("go", s["by_verdict"])


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        g = rg.ReadinessGate()
        g.check(rg.ReadinessInput(
            evidence_probability=0.5,
            evidence_gap=0.3,
            knowledge_freshness=0.6,
        ))
        self.assertEqual(g.reset(), 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        g = rg.ReadinessGate()
        d = g.check(rg.ReadinessInput(
            evidence_probability=0.9,
            evidence_gap=0.1,
            knowledge_freshness=0.9,
        ))
        out = d.as_dict()
        self.assertIn("verdict", out)
        self.assertIn("score", out)


if __name__ == "__main__":
    unittest.main()
