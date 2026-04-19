"""Launch predictor — deterministic signal tests.

The semantic signal requires a real Gemini key and a populated index,
so we stub it and focus on the math + branching logic.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.autonomous import launch_predictor as lp


class _FakeGoal:
    def __init__(self, **kw):
        self.manual_payload = kw.get("manual_payload") or None
        self.alibaba_url = kw.get("alibaba_url") or ""
        self.niche = kw.get("niche", "")
        self.copy_tone = kw.get("copy_tone", "friendly")
        self.target_price = kw.get("target_price")
        self.margin_floor = kw.get("margin_floor", 0.3)


class TestPriceFit(unittest.TestCase):
    def test_target_below_floor_scored_low(self) -> None:
        score, note = lp._price_fit(10.0, 11.0, 0.3)   # floor = 13
        self.assertEqual(score, 0.1)
        self.assertIn("below margin floor", note)

    def test_sweet_spot_40_to_75(self) -> None:
        # supplier 10, target 25 → margin (25-10)/25 = 60 %
        score, note = lp._price_fit(10.0, 25.0, 0.3)
        self.assertEqual(score, 0.9)
        self.assertIn("sweet spot", note)

    def test_margin_too_high(self) -> None:
        # supplier 1, target 100 → margin 99 %
        score, note = lp._price_fit(1.0, 100.0, 0.3)
        self.assertEqual(score, 0.35)
        self.assertIn(">", note)

    def test_unknown_prices_neutral(self) -> None:
        self.assertEqual(lp._price_fit(0, 0, 0.3), (0.5, ""))


class TestGrade(unittest.TestCase):
    def test_grade_bands(self) -> None:
        self.assertEqual(lp._grade_for(0.82), "A")
        self.assertEqual(lp._grade_for(0.65), "B")
        self.assertEqual(lp._grade_for(0.5), "C")
        self.assertEqual(lp._grade_for(0.2), "D")


class TestPredict(unittest.TestCase):
    def test_prediction_returns_values_in_range(self) -> None:
        goal = _FakeGoal(
            manual_payload={"title": "Test Widget", "price_usd": 5.0},
            niche="home",
            target_price=19.99,
            copy_tone="friendly",
        )
        with patch.object(lp, "_semantic_score", return_value=(0.6, [])):
            pred = lp.predict(goal)
        self.assertGreaterEqual(pred.win_probability, 0.0)
        self.assertLessEqual(pred.win_probability, 1.0)
        self.assertIn(pred.grade, {"A", "B", "C", "D"})
        self.assertIsInstance(pred.rationale, list)

    def test_weights_sum_to_one(self) -> None:
        total = sum(lp._WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_degenerate_goal_returns_baseline_ish(self) -> None:
        goal = _FakeGoal()
        with patch.object(lp, "_semantic_score", return_value=(0.5, [])):
            pred = lp.predict(goal)
        # Without any signal, the score should sit close to 0.5 (baseline).
        self.assertGreater(pred.win_probability, 0.35)
        self.assertLess(pred.win_probability, 0.7)


if __name__ == "__main__":
    unittest.main()
