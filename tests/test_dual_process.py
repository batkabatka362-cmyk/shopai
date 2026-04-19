"""Dual-process arbiter tests — routing / execution / telemetry."""
from __future__ import annotations

import unittest

from core.brain import dual_process as dp


def _s1(x):
    return f"fast({x})"


def _s2(x):
    return f"slow({x})"


class TestRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.a = dp.DualProcessArbiter(_s1, _s2)

    def test_high_stakes_always_slow(self) -> None:
        self.assertEqual(
            self.a.route_for(stakes=0.9, confidence=0.99),
            "system2",
        )

    def test_low_confidence_always_slow(self) -> None:
        self.assertEqual(
            self.a.route_for(stakes=0.1, confidence=0.2),
            "system2",
        )

    def test_urgent_cheap_uses_fast(self) -> None:
        self.assertEqual(
            self.a.route_for(stakes=0.1, confidence=0.5, urgency=3),
            "system1",
        )

    def test_high_confidence_uses_fast(self) -> None:
        self.assertEqual(
            self.a.route_for(stakes=0.1, confidence=0.9),
            "system1",
        )

    def test_middle_case_slow(self) -> None:
        self.assertEqual(
            self.a.route_for(stakes=0.3, confidence=0.6),
            "system2",
        )


class TestDecide(unittest.TestCase):
    def setUp(self) -> None:
        self.a = dp.DualProcessArbiter(_s1, _s2)

    def test_decide_routes_to_fast(self) -> None:
        d = self.a.decide(42, stakes=0.1, confidence=0.9)
        self.assertEqual(d.route, "system1")
        self.assertEqual(d.answer, "fast(42)")

    def test_decide_routes_to_slow(self) -> None:
        d = self.a.decide(42, stakes=0.8, confidence=0.5)
        self.assertEqual(d.route, "system2")
        self.assertEqual(d.answer, "slow(42)")

    def test_override_forces_route(self) -> None:
        d = self.a.decide(1, stakes=0.1, confidence=0.99,
                           override="system2")
        self.assertEqual(d.route, "system2")

    def test_fallback_when_primary_raises(self) -> None:
        def broken(x):
            raise RuntimeError("s1 down")
        a = dp.DualProcessArbiter(broken, _s2)
        d = a.decide("x", stakes=0.1, confidence=0.99)
        # Forced into system1 by routing, fell back to system2
        self.assertEqual(d.route, "system2")
        self.assertEqual(d.answer, "slow(x)")

    def test_both_raising_propagates(self) -> None:
        def bad(x):
            raise RuntimeError("down")
        a = dp.DualProcessArbiter(bad, bad)
        with self.assertRaises(RuntimeError):
            a.decide("x", stakes=0.5, confidence=0.5)


class TestTelemetry(unittest.TestCase):
    def test_stats_accumulate_per_route(self) -> None:
        a = dp.DualProcessArbiter(_s1, _s2)
        a.decide(1, stakes=0.1, confidence=0.9)
        a.decide(2, stakes=0.1, confidence=0.9)
        a.decide(3, stakes=0.8, confidence=0.5)
        stats = a.stats()
        self.assertEqual(stats.system1_count, 2)
        self.assertEqual(stats.system2_count, 1)

    def test_reset_clears_stats(self) -> None:
        a = dp.DualProcessArbiter(_s1, _s2)
        a.decide(1, stakes=0.1, confidence=0.9)
        a.reset_stats()
        self.assertEqual(a.stats().system1_count, 0)


class TestRationale(unittest.TestCase):
    def test_rationale_references_reason(self) -> None:
        a = dp.DualProcessArbiter(_s1, _s2)
        d = a.decide(1, stakes=0.9, confidence=0.5)
        self.assertIn("stakes", d.rationale)
        self.assertIn("deliberate", d.rationale)

    def test_fast_path_rationale(self) -> None:
        a = dp.DualProcessArbiter(_s1, _s2)
        d = a.decide(1, stakes=0.1, confidence=0.95)
        self.assertIn("confidence", d.rationale)
        self.assertIn("fast", d.rationale)


class TestConfidenceFromPrecedents(unittest.TestCase):
    def test_zero_matches_zero_confidence(self) -> None:
        self.assertEqual(
            dp.confidence_from_precedents(0, 3.0), 0.0,
        )

    def test_many_high_score_low_variance(self) -> None:
        c = dp.confidence_from_precedents(
            n_matches=20, mean_outcome_score=4.5, variance=0.1,
        )
        self.assertGreater(c, 0.7)

    def test_few_matches_low_confidence(self) -> None:
        c = dp.confidence_from_precedents(1, 3.0)
        self.assertLess(c, 0.5)


class TestStakesFromDollarRisk(unittest.TestCase):
    def test_below_cap_scales_linearly(self) -> None:
        self.assertAlmostEqual(
            dp.stakes_from_dollar_risk(25, cost_cap_usd=100), 0.25,
        )

    def test_above_cap_clamps(self) -> None:
        self.assertEqual(
            dp.stakes_from_dollar_risk(500, cost_cap_usd=100), 1.0,
        )


if __name__ == "__main__":
    unittest.main()
