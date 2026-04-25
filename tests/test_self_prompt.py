"""Self-prompt generator tests."""
from __future__ import annotations

import unittest

from core.brain import self_prompt as sp


class TestKillSpike(unittest.TestCase):
    def test_fires_on_many_kills(self) -> None:
        sit = sp.Situation(kills_last_7d=5, scales_last_7d=1)
        qs = sp.gen_kill_spike(sit)
        self.assertEqual(len(qs), 1)
        self.assertIn("killed 5", qs[0].text)
        self.assertEqual(qs[0].suggested_tool, "counterfactual")

    def test_silent_on_low_kills(self) -> None:
        sit = sp.Situation(kills_last_7d=2, scales_last_7d=2)
        self.assertEqual(len(sp.gen_kill_spike(sit)), 0)


class TestCalibration(unittest.TestCase):
    def test_fires_below_threshold(self) -> None:
        sit = sp.Situation(calibration_hit_rate=0.40)
        qs = sp.gen_confidence_drop(sit)
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].suggested_tool, "metacognition")

    def test_silent_above_threshold(self) -> None:
        sit = sp.Situation(calibration_hit_rate=0.70)
        self.assertEqual(len(sp.gen_confidence_drop(sit)), 0)


class TestStagnantGoal(unittest.TestCase):
    def test_fires_after_three_days(self) -> None:
        sit = sp.Situation(stagnant_goals=[
            {"id": "g1", "title": "Scale audio", "days_idle": 5},
        ])
        qs = sp.gen_stagnant_goal(sit)
        self.assertEqual(len(qs), 1)
        self.assertIn("Scale audio", qs[0].text)

    def test_silent_if_recent(self) -> None:
        sit = sp.Situation(stagnant_goals=[
            {"id": "g2", "title": "x", "days_idle": 1},
        ])
        self.assertEqual(len(sp.gen_stagnant_goal(sit)), 0)


class TestSurprise(unittest.TestCase):
    def test_fires_on_high_magnitude(self) -> None:
        sit = sp.Situation(unresolved_surprises=[
            {"id": 7, "signature": "roas:audio", "magnitude": 0.8},
        ])
        qs = sp.gen_unresolved_surprise(sit)
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].suggested_tool, "debate")

    def test_silent_on_low_magnitude(self) -> None:
        sit = sp.Situation(unresolved_surprises=[
            {"id": 7, "magnitude": 0.2},
        ])
        self.assertEqual(len(sp.gen_unresolved_surprise(sit)), 0)


class TestIdleSkill(unittest.TestCase):
    def test_fires_on_two_weeks_idle(self) -> None:
        sit = sp.Situation(idle_skills=[
            {"name": "content.write_copy", "days_since_use": 20},
        ])
        qs = sp.gen_idle_skill(sit)
        self.assertEqual(len(qs), 1)


class TestOverdueHypothesis(unittest.TestCase):
    def test_fires_on_overdue(self) -> None:
        sit = sp.Situation(overdue_hypotheses=[
            {"id": "h1", "subject": "price_bump", "days_overdue": 3},
        ])
        qs = sp.gen_hypothesis_overdue(sit)
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0].suggested_tool, "hypothesis")


class TestCompose(unittest.TestCase):
    def test_compose_picks_top_k_by_priority(self) -> None:
        sit = sp.Situation(
            kills_last_7d=6, scales_last_7d=1,
            calibration_hit_rate=0.40,
            stagnant_goals=[{"id": "g1", "title": "x", "days_idle": 1}],  # filtered
            unresolved_surprises=[
                {"id": 1, "magnitude": 0.9, "signature": "s1"},
            ],
        )
        qs = sp.compose(sit, top_k=2)
        self.assertEqual(len(qs), 2)
        # Sorted by priority descending.
        self.assertGreaterEqual(qs[0].priority, qs[1].priority)

    def test_compose_applies_writer(self) -> None:
        sit = sp.Situation(kills_last_7d=5, scales_last_7d=0)
        qs = sp.compose(
            sit, top_k=1,
            writer=lambda q: f"POLISHED: {q.text[:20]}",
        )
        self.assertEqual(len(qs), 1)
        self.assertTrue(qs[0].text.startswith("POLISHED:"))

    def test_compose_empty_situation_returns_empty(self) -> None:
        qs = sp.compose(sp.Situation(), top_k=5)
        self.assertEqual(len(qs), 0)


if __name__ == "__main__":
    unittest.main()
