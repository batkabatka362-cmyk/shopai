"""Counterfactual engine — matching + regret tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from core.brain import counterfactual as cf


class TestDefaults(unittest.TestCase):
    def test_opposite_of_kill_is_scale_or_hold(self) -> None:
        self.assertIn(cf._default_opposite("kill"), {"scale", "hold"})

    def test_opposite_of_unknown_defaults_to_hold(self) -> None:
        self.assertEqual(cf._default_opposite("mystery"), "hold")


class TestBlank(unittest.TestCase):
    def test_blank_has_zero_fields(self) -> None:
        report = cf._blank("l1", "nothing found")
        self.assertEqual(report.launch_id, "l1")
        self.assertEqual(report.realised_revenue, 0.0)
        self.assertIn("nothing found", report.narrative)


class TestWhatIf(unittest.TestCase):
    def _mock_env(self, anchor_verdict: str, neighbours_data: list[dict]):
        """Build a mock evaluator + niche_map pair."""
        anchor_mock = MagicMock()
        anchor_mock.launch_id = "target"
        anchor_mock.verdict = anchor_verdict
        anchor_mock.estimated_roas = 1.2
        anchor_mock.revenue_usd = 40.0
        anchor_mock.ad_budget_day = 20.0

        neigh_mocks = []
        for n in neighbours_data:
            m = MagicMock()
            m.launch_id = n["launch_id"]
            m.verdict = n["verdict"]
            m.estimated_roas = n.get("roas", 2.0)
            m.revenue_usd = n.get("revenue_usd", 100.0)
            m.ad_budget_day = n.get("ad_budget_day", 20.0)
            neigh_mocks.append(m)

        fake_report = MagicMock()
        fake_report.kill_recommendations = [anchor_mock] + [n for n in neigh_mocks
                                                            if n.verdict == "kill"]
        fake_report.scale_recommendations = [n for n in neigh_mocks
                                             if n.verdict == "scale"]
        fake_report.monitor_recommendations = [n for n in neigh_mocks
                                               if n.verdict in ("hold",
                                                                "waiting_for_data")]
        niches = {"target": "audio"}
        for n in neighbours_data:
            niches[n["launch_id"]] = "audio"
        return fake_report, niches

    def test_regret_positive_when_alt_worse(self) -> None:
        """Alt-history 'scale' would have earned $50, realised 'kill'
        earned $40 — regret +10."""
        report, niches = self._mock_env(
            anchor_verdict="kill",
            neighbours_data=[
                {"launch_id": "n1", "verdict": "scale",
                 "revenue_usd": 40},
                {"launch_id": "n2", "verdict": "scale",
                 "revenue_usd": 50},
                {"launch_id": "n3", "verdict": "scale",
                 "revenue_usd": 60},
            ],
        )
        with patch("core.autonomous.launch_evaluator.evaluate",
                   return_value=report), \
             patch("core.autonomous.self_critic._niche_map",
                   return_value=niches), \
             patch.object(cf, "_persist"):
            out = cf.what_if("target", alt_verdict="scale")
        self.assertEqual(out.counterfactual_verdict, "scale")
        self.assertEqual(out.neighbours, 3)
        self.assertAlmostEqual(out.cf_revenue_mean, 50.0)
        self.assertAlmostEqual(out.regret, 40.0 - 50.0)

    def test_no_matching_neighbours_returns_blank(self) -> None:
        report, niches = self._mock_env(
            anchor_verdict="kill", neighbours_data=[],
        )
        with patch("core.autonomous.launch_evaluator.evaluate",
                   return_value=report), \
             patch("core.autonomous.self_critic._niche_map",
                   return_value=niches), \
             patch.object(cf, "_persist"):
            out = cf.what_if("target")
        self.assertEqual(out.neighbours, 0)
        self.assertIn("no matched", out.narrative)

    def test_missing_anchor_returns_blank(self) -> None:
        with patch("core.brain.counterfactual._anchor", return_value=None):
            out = cf.what_if("ghost")
        self.assertEqual(out.neighbours, 0)
        self.assertIn("no anchor", out.narrative)


class TestBudgetFilter(unittest.TestCase):
    def test_neighbours_outside_budget_band_dropped(self) -> None:
        anchor = {"launch_id": "target", "verdict": "kill",
                  "niche": "audio", "ad_budget_day": 20.0}

        scale_ok = MagicMock(launch_id="ok", verdict="scale",
                             estimated_roas=2.0, revenue_usd=100,
                             ad_budget_day=25.0)
        scale_big = MagicMock(launch_id="too_big", verdict="scale",
                              estimated_roas=2.0, revenue_usd=500,
                              ad_budget_day=200.0)   # 10× too big
        scale_tiny = MagicMock(launch_id="too_small", verdict="scale",
                               estimated_roas=2.0, revenue_usd=2,
                               ad_budget_day=1.0)    # 20× too small

        fake_report = MagicMock()
        fake_report.kill_recommendations = []
        fake_report.scale_recommendations = [scale_ok, scale_big, scale_tiny]
        fake_report.monitor_recommendations = []

        with patch("core.autonomous.launch_evaluator.evaluate",
                   return_value=fake_report), \
             patch("core.autonomous.self_critic._niche_map",
                   return_value={"ok": "audio", "too_big": "audio",
                                 "too_small": "audio"}):
            matches = cf._matched_neighbours(anchor, "scale")
        self.assertEqual([m["launch_id"] for m in matches], ["ok"])


if __name__ == "__main__":
    unittest.main()
