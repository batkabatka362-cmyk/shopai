"""Resource contention scheduler tests."""
from __future__ import annotations

import unittest

from core.system import resource_contention as rc


class TestSubmit(unittest.TestCase):
    def setUp(self) -> None:
        self.s = rc.ResourceScheduler()

    def test_submit_returns_id(self) -> None:
        jid = self.s.submit("groq", lambda: "ok")
        self.assertTrue(jid)

    def test_blank_resource_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.s.submit("", lambda: None)

    def test_unknown_priority_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.s.submit("r", lambda: None, priority="super")

    def test_negative_cost_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.s.submit("r", lambda: None, cost=-1)


class TestPriorityOrder(unittest.TestCase):
    def test_critical_drains_before_normal(self) -> None:
        s = rc.ResourceScheduler()
        s.submit("r", lambda: "low", priority="low")
        s.submit("r", lambda: "critical", priority="critical")
        s.submit("r", lambda: "normal", priority="normal")
        rep = s.drain("r", budget=10, max_jobs=1)
        self.assertEqual(rep.results[0].output, "critical")

    def test_fifo_within_same_priority(self) -> None:
        s = rc.ResourceScheduler()
        s.submit("r", lambda: "first", priority="normal")
        s.submit("r", lambda: "second", priority="normal")
        rep = s.drain("r", budget=10)
        self.assertEqual(rep.results[0].output, "first")
        self.assertEqual(rep.results[1].output, "second")


class TestBudget(unittest.TestCase):
    def test_budget_exhausts(self) -> None:
        s = rc.ResourceScheduler()
        for _ in range(5):
            s.submit("r", lambda: "ok", cost=3)
        rep = s.drain("r", budget=10)
        self.assertEqual(rep.jobs_run, 3)
        self.assertAlmostEqual(rep.spent, 9.0)
        # Remaining 2 jobs stay queued for next drain
        self.assertEqual(s.pending_count("r"), 2)

    def test_zero_budget_runs_none(self) -> None:
        s = rc.ResourceScheduler()
        s.submit("r", lambda: "ok")
        rep = s.drain("r", budget=0)
        self.assertEqual(rep.jobs_run, 0)

    def test_max_jobs_cap(self) -> None:
        s = rc.ResourceScheduler()
        for _ in range(5):
            s.submit("r", lambda: "ok", cost=0.1)
        rep = s.drain("r", budget=100, max_jobs=2)
        self.assertEqual(rep.jobs_run, 2)


class TestFailure(unittest.TestCase):
    def test_failed_job_isolated(self) -> None:
        s = rc.ResourceScheduler()
        def boom():
            raise RuntimeError("bad")
        s.submit("r", boom, priority="high")
        s.submit("r", lambda: "ok")
        rep = s.drain("r", budget=10)
        statuses = [r.status for r in rep.results]
        self.assertIn("failed", statuses)
        self.assertIn("ok", statuses)

    def test_failed_job_consumes_no_budget(self) -> None:
        s = rc.ResourceScheduler()
        def boom():
            raise RuntimeError("x")
        s.submit("r", boom, cost=5)
        rep = s.drain("r", budget=10)
        self.assertEqual(rep.spent, 0.0)


class TestCancel(unittest.TestCase):
    def test_cancel_skips_job(self) -> None:
        s = rc.ResourceScheduler()
        jid = s.submit("r", lambda: "nope")
        self.assertTrue(s.cancel(jid))
        rep = s.drain("r", budget=10)
        self.assertEqual(rep.jobs_run, 0)


class TestMultipleResources(unittest.TestCase):
    def test_independent_queues(self) -> None:
        s = rc.ResourceScheduler()
        s.submit("groq", lambda: "groq")
        s.submit("shopify", lambda: "shopify")
        rep_groq = s.drain("groq", budget=10)
        rep_shopify = s.drain("shopify", budget=10)
        self.assertEqual(rep_groq.results[0].output, "groq")
        self.assertEqual(rep_shopify.results[0].output, "shopify")


class TestStats(unittest.TestCase):
    def test_stats_reports_counts(self) -> None:
        s = rc.ResourceScheduler()
        s.submit("r", lambda: 1, priority="critical")
        s.submit("r", lambda: 1, priority="normal")
        stats = s.stats()
        self.assertEqual(stats["queues"]["r"]["critical"], 1)
        self.assertEqual(stats["queues"]["r"]["normal"], 1)


class TestDrainOnUnknownResource(unittest.TestCase):
    def test_empty_drain(self) -> None:
        s = rc.ResourceScheduler()
        rep = s.drain("never_used", budget=5)
        self.assertEqual(rep.jobs_run, 0)


if __name__ == "__main__":
    unittest.main()
