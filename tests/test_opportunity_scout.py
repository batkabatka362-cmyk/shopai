"""Opportunity scout — unit tests for individual scouts."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from core.autonomous import opportunity_scout as os


class TestScoutKillCandidates(unittest.TestCase):
    def test_adds_every_kill(self) -> None:
        fake = MagicMock()
        fake.kill_recommendations = [
            MagicMock(launch_id="l1", estimated_roas=0.5,
                      reason="low roas"),
            MagicMock(launch_id="l2", estimated_roas=1.0,
                      reason="low roas"),
        ]
        fake.monitor_recommendations = []
        fake.scale_recommendations = []
        with patch("core.autonomous.launch_evaluator.evaluate",
                   return_value=fake):
            report = os.DigestReport(date="2026-01-01")
            os._find_kill_candidates(report)
        kinds = [o.kind for o in report.opportunities]
        self.assertEqual(kinds, ["kill", "kill"])


class TestScoutScaleCandidates(unittest.TestCase):
    def test_only_when_above_mean_plus_sigma(self) -> None:
        fake = MagicMock()
        # Three launches, one far above the mean
        def make(lid, roas, verdict):
            m = MagicMock()
            m.launch_id = lid
            m.estimated_roas = roas
            m.verdict = verdict
            m.days_live = 4.0
            return m
        monitors = [make("a", 2.0, "hold"), make("b", 2.1, "hold"),
                    make("c", 2.2, "hold"), make("d", 5.0, "hold")]
        fake.monitor_recommendations = monitors
        fake.kill_recommendations = []
        fake.scale_recommendations = []
        with patch("core.autonomous.launch_evaluator.evaluate",
                   return_value=fake), \
             patch("core.autonomous.self_critic._niche_map",
                   return_value={"a": "audio", "b": "audio", "c": "audio",
                                 "d": "audio"}):
            report = os.DigestReport(date="2026-01-01")
            os._find_scale_candidates(report)
        ids = [o.target_id for o in report.opportunities]
        self.assertEqual(ids, ["d"])


class TestDigestReport(unittest.TestCase):
    def test_counts_by_kind(self) -> None:
        r = os.DigestReport(date="2026-01-01")
        r.opportunities = [
            os.Opportunity(kind="kill", target_id="l1", headline=""),
            os.Opportunity(kind="kill", target_id="l2", headline=""),
            os.Opportunity(kind="scale", target_id="l3", headline=""),
        ]
        self.assertEqual(r._counts_by_kind(), {"kill": 2, "scale": 1})

    def test_as_dict_round_trip(self) -> None:
        r = os.DigestReport(date="x")
        r.opportunities.append(os.Opportunity(
            kind="kill", target_id="l1", headline="h", score=1.2,
        ))
        d = r.as_dict()
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["opportunities"][0]["score"], 1.2)


class TestFullScout(unittest.TestCase):
    def test_scout_returns_report_without_exception(self) -> None:
        fake_eval = MagicMock()
        fake_eval.kill_recommendations = []
        fake_eval.scale_recommendations = []
        fake_eval.monitor_recommendations = []
        with patch("core.autonomous.launch_evaluator.evaluate",
                   return_value=fake_eval), \
             patch("core.autonomous.self_critic._niche_map",
                   return_value={}), \
             patch("core.brain.transfer_learner.retrieve_for_niche",
                   return_value=[]), \
             patch.object(os, "_find_underutilised_rules"), \
             patch.object(os, "_find_competitor_openings"), \
             patch.object(os, "_persist"):
            report = os.scout(include_narrative=False)
        self.assertEqual(report.opportunities, [])
        self.assertEqual(report.narrative, "")


if __name__ == "__main__":
    unittest.main()
