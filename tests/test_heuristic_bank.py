"""Heuristic bank tests."""
from __future__ import annotations

import unittest

from core.brain import heuristic_bank as hb


class TestEvaluate(unittest.TestCase):
    def setUp(self) -> None:
        self.b = hb.HeuristicBank()

    def test_bad_ctx_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.evaluate("not a dict")  # type: ignore[arg-type]

    def test_roas_kill_fires(self) -> None:
        v = self.b.evaluate({
            "roas": 1.2, "days_live": 4,
        })
        self.assertIsNotNone(v)
        self.assertEqual(v.heuristic_id, "roas_kill")
        self.assertEqual(v.action, "act")

    def test_roas_kill_no_fire_early(self) -> None:
        v = self.b.evaluate({
            "roas": 1.2, "days_live": 1,
        })
        # day 1 < 3 day threshold
        self.assertIsNone(v)

    def test_cpm_spike_alert(self) -> None:
        v = self.b.evaluate({
            "roas": 2.0,
            "days_live": 1,
            "cpm": 50, "cpm_baseline": 20,
        })
        self.assertEqual(v.heuristic_id, "cpm_spike")

    def test_stockout_soon(self) -> None:
        v = self.b.evaluate({
            "roas": 2.0, "days_live": 1,
            "inventory_units": 10, "daily_sales": 10,
        })
        self.assertEqual(v.heuristic_id, "stockout_soon")

    def test_churn_risk(self) -> None:
        v = self.b.evaluate({
            "roas": 2.0, "days_live": 1,
            "days_inactive": 45,
        })
        self.assertEqual(v.heuristic_id, "churn_risk")

    def test_no_match_none(self) -> None:
        self.assertIsNone(self.b.evaluate({"roas": 3.0}))

    def test_priority_order(self) -> None:
        # both cpm_spike (prio 20) and roas_kill (prio 10) match
        # roas_kill should win
        v = self.b.evaluate({
            "roas": 1.0, "days_live": 5,
            "cpm": 50, "cpm_baseline": 20,
        })
        self.assertEqual(v.heuristic_id, "roas_kill")


class TestRegistry(unittest.TestCase):
    def test_register_custom(self) -> None:
        def pred(ctx):
            return ctx.get("kind") == "custom"

        h = hb.Heuristic(
            id="custom", name="c",
            predicate=pred,
            action="act",
            reason_template="custom fire",
            priority=1,
        )
        b = hb.HeuristicBank()
        b.register(h)
        v = b.evaluate({"kind": "custom"})
        self.assertEqual(v.heuristic_id, "custom")

    def test_unregister(self) -> None:
        b = hb.HeuristicBank()
        self.assertTrue(b.unregister("roas_kill"))
        # Now ROAS<1.5 doesn't fire
        self.assertIsNone(b.evaluate({
            "roas": 1.0, "days_live": 5,
        }))

    def test_unregister_unknown(self) -> None:
        b = hb.HeuristicBank()
        self.assertFalse(b.unregister("nope"))


class TestFailingPredicate(unittest.TestCase):
    def test_raising_predicate_skipped(self) -> None:
        def boom(_ctx):
            raise RuntimeError("bug")

        h = hb.Heuristic(
            id="b", name="boom",
            predicate=boom, action="act",
            reason_template="x", priority=1,
        )
        b = hb.HeuristicBank(heuristics=[h])
        # Should return None, not crash
        self.assertIsNone(b.evaluate({}))


class TestFeedback(unittest.TestCase):
    def test_record_outcome(self) -> None:
        b = hb.HeuristicBank()
        b.evaluate({"roas": 1.0, "days_live": 5})
        self.assertTrue(b.record_outcome(
            "roas_kill", was_correct=True,
        ))
        stats = b.stats("roas_kill")
        self.assertEqual(stats.hits, 1)
        self.assertEqual(stats.hit_rate, 1.0)

    def test_record_outcome_unknown(self) -> None:
        b = hb.HeuristicBank()
        self.assertFalse(b.record_outcome(
            "nope", was_correct=True,
        ))


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        b = hb.HeuristicBank()
        b.evaluate({"roas": 1.0, "days_live": 5})
        s = b.stats()
        self.assertGreaterEqual(s["heuristics"], 4)
        self.assertEqual(s["fires_total"], 1)


class TestHistory(unittest.TestCase):
    def test_recent_verdicts(self) -> None:
        b = hb.HeuristicBank()
        for _ in range(3):
            b.evaluate({"roas": 1.0, "days_live": 5})
        self.assertEqual(len(b.recent_verdicts(limit=2)), 2)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        b = hb.HeuristicBank()
        b.evaluate({"roas": 1.0, "days_live": 5})
        n = b.reset()
        self.assertEqual(n, 1)
        self.assertEqual(b.stats("roas_kill").fires, 0)


class TestDict(unittest.TestCase):
    def test_verdict_serialises(self) -> None:
        b = hb.HeuristicBank()
        v = b.evaluate({"roas": 1.0, "days_live": 5})
        d = v.as_dict()
        self.assertEqual(d["heuristic_id"], "roas_kill")

    def test_stats_serialises(self) -> None:
        b = hb.HeuristicBank()
        b.evaluate({"roas": 1.0, "days_live": 5})
        s = b.stats("roas_kill")
        d = s.as_dict()
        self.assertIn("hit_rate", d)


if __name__ == "__main__":
    unittest.main()
