"""Goal compiler tests."""
from __future__ import annotations

import unittest

from core.brain import goal_compiler as gc


class TestEmpty(unittest.TestCase):
    def test_empty_returns_empty(self) -> None:
        c = gc.compile_goal("")
        self.assertEqual(c.subgoals, [])
        self.assertEqual(c.kpis, [])

    def test_no_verbs_falls_back_investigate(self) -> None:
        c = gc.compile_goal("the price is right")
        self.assertEqual(len(c.subgoals), 1)
        self.assertEqual(c.subgoals[0].name, "investigate")


class TestUrlExtraction(unittest.TestCase):
    def test_url_captured(self) -> None:
        c = gc.compile_goal(
            "Sync https://alibaba.com/p/123 then publish",
        )
        self.assertIn("https://alibaba.com/p/123", c.references["urls"])


class TestBudget(unittest.TestCase):
    def test_dollar_amount_captured(self) -> None:
        c = gc.compile_goal("Launch ads at $20/day")
        self.assertEqual(c.budget["ads_daily_usd"], 20.0)

    def test_dollar_with_decimals(self) -> None:
        c = gc.compile_goal("scale to $19.50/day")
        self.assertAlmostEqual(c.budget["ads_daily_usd"], 19.50)


class TestKpiExtraction(unittest.TestCase):
    def test_roas_kill(self) -> None:
        c = gc.compile_goal("3 days monitor, kill if ROAS < 1.5")
        roas = next(k for k in c.kpis if k.name == "roas")
        self.assertEqual(roas.threshold, 1.5)
        self.assertEqual(roas.direction, "min")
        self.assertEqual(roas.on_breach, "kill")
        self.assertAlmostEqual(roas.window_days, 3.0)

    def test_cpa_above_alert(self) -> None:
        c = gc.compile_goal("Alert if CPA > $25 over 7 days")
        cpa = next(k for k in c.kpis if k.name == "cpa")
        self.assertEqual(cpa.threshold, 25.0)
        self.assertEqual(cpa.direction, "max")
        self.assertEqual(cpa.on_breach, "alert")
        self.assertAlmostEqual(cpa.window_days, 7.0)


class TestSubgoalPipeline(unittest.TestCase):
    def test_full_launch_pipeline(self) -> None:
        c = gc.compile_goal(
            "Sync from Alibaba, publish on Shopify, "
            "make a video, launch ads $15/day, monitor for 3 days, "
            "kill if ROAS<1.5",
        )
        names = [s.name for s in c.subgoals]
        self.assertEqual(
            names,
            ["ingest", "publish", "create_video",
             "ads_launch", "monitor", "kill_check"],
        )

    def test_subgoals_chain_dependencies(self) -> None:
        c = gc.compile_goal(
            "Sync product, publish to shopify, launch ads",
        )
        self.assertEqual(c.subgoals[0].depends_on, ())
        self.assertEqual(c.subgoals[1].depends_on, ("ingest",))
        self.assertEqual(c.subgoals[2].depends_on, ("publish",))

    def test_verb_synonyms_recognised(self) -> None:
        c = gc.compile_goal("import the product and post it to shopify")
        names = [s.name for s in c.subgoals]
        self.assertIn("ingest", names)
        self.assertIn("publish", names)

    def test_canonical_order_enforced(self) -> None:
        c = gc.compile_goal("Kill bad ads after publish, sync first")
        names = [s.name for s in c.subgoals]
        # Canonical order: sync(ingest) → publish → kill
        self.assertEqual(
            names, ["ingest", "publish", "kill_check"],
        )


class TestMonitorWindow(unittest.TestCase):
    def test_monitor_uses_first_duration(self) -> None:
        c = gc.compile_goal(
            "monitor 7 days then kill on roas<1.5",
        )
        monitor = next(s for s in c.subgoals if s.name == "monitor")
        self.assertEqual(monitor.deadline_s, 7 * 86_400.0)
        kill = next(s for s in c.subgoals if s.name == "kill_check")
        self.assertEqual(kill.deadline_s, 7 * 86_400.0)


class TestTrail(unittest.TestCase):
    def test_trail_records_matches(self) -> None:
        c = gc.compile_goal(
            "Sync https://x then publish at $20/day, monitor 3 days",
        )
        slots = {entry["slot"] for entry in c.trail}
        self.assertIn("urls", slots)
        self.assertIn("ads_daily_usd", slots)
        self.assertIn("monitor_window_s", slots)


class TestDict(unittest.TestCase):
    def test_compiled_goal_serialises(self) -> None:
        c = gc.compile_goal("Sync and publish")
        d = c.as_dict()
        self.assertIn("subgoals", d)
        self.assertIn("kpis", d)
        self.assertIn("trail", d)


class TestSecondsFor(unittest.TestCase):
    def test_minutes(self) -> None:
        self.assertEqual(gc._seconds_for(5, "min"), 300.0)

    def test_hours(self) -> None:
        self.assertEqual(gc._seconds_for(2, "hr"), 7200.0)

    def test_days(self) -> None:
        self.assertEqual(gc._seconds_for(3, "days"), 3 * 86_400.0)

    def test_weeks(self) -> None:
        self.assertEqual(gc._seconds_for(1, "week"), 7 * 86_400.0)


if __name__ == "__main__":
    unittest.main()
