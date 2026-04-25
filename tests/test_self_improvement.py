"""Self-improvement engine tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import self_improvement as si


class TestThresholdTune(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.e = si.SelfImprovementEngine(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_raises_threshold_when_refunds_cluster_above(self) -> None:
        proposals = self.e.detect(si.Signals(niche_kill_outcomes=[
            {"niche": "audio", "current_threshold": 1.5,
             "refund_roas_band": [1.6, 1.7]},
        ]))
        kinds = [p.kind for p in proposals]
        self.assertIn("threshold_tune", kinds)
        tt = next(p for p in proposals if p.kind == "threshold_tune")
        self.assertGreater(tt.after, tt.before)

    def test_silent_when_refunds_below_threshold(self) -> None:
        proposals = self.e.detect(si.Signals(niche_kill_outcomes=[
            {"niche": "audio", "current_threshold": 1.5,
             "refund_roas_band": [0.8, 1.0]},
        ]))
        self.assertFalse(
            any(p.kind == "threshold_tune" for p in proposals),
        )


class TestSkillPriority(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.e = si.SelfImprovementEngine(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_raises_priority_for_idle_strong_skill(self) -> None:
        proposals = self.e.detect(si.Signals(skill_usage=[
            {"name": "email.copy", "wins": 9, "uses": 10,
             "days_since_use": 20, "priority": 1.0},
        ]))
        sp = next(p for p in proposals if p.kind == "skill_priority")
        self.assertGreater(sp.after, sp.before)

    def test_lowers_priority_for_failing_skill(self) -> None:
        proposals = self.e.detect(si.Signals(skill_usage=[
            {"name": "broken.tool", "wins": 2, "uses": 20,
             "days_since_use": 1, "priority": 1.0},
        ]))
        sp = next(p for p in proposals if p.kind == "skill_priority")
        self.assertLess(sp.after, sp.before)


class TestRuleRetirement(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.e = si.SelfImprovementEngine(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_flags_low_success_rule(self) -> None:
        proposals = self.e.detect(si.Signals(rule_performance=[
            {"id": "R-42", "fires": 30, "successes": 6},
        ]))
        self.assertTrue(
            any(p.kind == "rule_retirement" for p in proposals),
        )

    def test_ignores_low_fire_rule(self) -> None:
        proposals = self.e.detect(si.Signals(rule_performance=[
            {"id": "R-new", "fires": 5, "successes": 1},
        ]))
        self.assertFalse(
            any(p.kind == "rule_retirement" for p in proposals),
        )


class TestMissingRule(unittest.TestCase):
    def test_proposes_when_cluster_meets_threshold(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        e = si.SelfImprovementEngine(Path(tmp.name) / "s.db")
        proposals = e.detect(si.Signals(missing_rule_clusters=[
            {"feature": "tone:urgent + niche:audio",
             "count": 8, "outcome": "scale"},
        ]))
        self.assertTrue(
            any(p.kind == "missing_rule" for p in proposals),
        )
        tmp.cleanup()


class TestAlphaAdjust(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.e = si.SelfImprovementEngine(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_lowers_alpha_when_preference_dominates(self) -> None:
        proposals = self.e.detect(si.Signals(reward_model_stats={
            "kpi_weight": 0.5, "preference_weight_share": 0.9,
        }))
        aa = next(p for p in proposals if p.kind == "alpha_adjust")
        self.assertLess(aa.after, aa.before)

    def test_raises_alpha_when_preference_minimal(self) -> None:
        proposals = self.e.detect(si.Signals(reward_model_stats={
            "kpi_weight": 0.4, "preference_weight_share": 0.05,
        }))
        aa = next(p for p in proposals if p.kind == "alpha_adjust")
        self.assertGreater(aa.after, aa.before)


class TestLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.e = si.SelfImprovementEngine(Path(self._tmp.name) / "s.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_apply_then_score(self) -> None:
        proposals = self.e.detect(si.Signals(rule_performance=[
            {"id": "R-bad", "fires": 50, "successes": 10},
        ]))
        pid = proposals[0].id
        self.assertTrue(self.e.apply(pid))
        self.assertTrue(self.e.score_outcome(pid, 0.7))
        stats = self.e.stats()
        self.assertEqual(stats["by_status"].get("applied"), 1)
        self.assertAlmostEqual(stats["avg_outcome_score"], 0.7)

    def test_reject_does_not_apply(self) -> None:
        proposals = self.e.detect(si.Signals(rule_performance=[
            {"id": "R-x", "fires": 50, "successes": 10},
        ]))
        pid = proposals[0].id
        self.assertTrue(self.e.reject(pid))
        pend = self.e.pending()
        self.assertFalse(any(p.id == pid for p in pend))


if __name__ == "__main__":
    unittest.main()
