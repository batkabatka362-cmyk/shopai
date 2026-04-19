"""Self-test harness tests."""
from __future__ import annotations

import unittest

from core.brain import self_test_harness as sth


class TestHealthCheck(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            sth.HealthCheck(
                name="", category="memory",
                run=lambda: sth.CheckOutcome(ok=True),
            )

    def test_bad_category_raises(self) -> None:
        with self.assertRaises(ValueError):
            sth.HealthCheck(
                name="x", category="bogus",  # type: ignore[arg-type]
                run=lambda: sth.CheckOutcome(ok=True),
            )

    def test_bad_severity_raises(self) -> None:
        with self.assertRaises(ValueError):
            sth.HealthCheck(
                name="x", category="memory",
                run=lambda: sth.CheckOutcome(ok=True),
                severity="fatal",  # type: ignore[arg-type]
            )


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.h = sth.SelfTestHarness()
        self.c = sth.HealthCheck(
            name="x", category="memory",
            run=lambda: sth.CheckOutcome(ok=True),
        )

    def test_register_and_list(self) -> None:
        self.h.register(self.c)
        self.assertEqual(len(self.h.checks()), 1)

    def test_duplicate_rejected(self) -> None:
        self.h.register(self.c)
        with self.assertRaises(ValueError):
            self.h.register(self.c)

    def test_overwrite_allowed(self) -> None:
        self.h.register(self.c)
        # Replace with a different check using same name
        replaced = sth.HealthCheck(
            name="x", category="performance",
            run=lambda: sth.CheckOutcome(ok=True),
        )
        self.h.register(replaced, overwrite=True)
        self.assertEqual(
            self.h.checks()[0].category, "performance",
        )

    def test_unregister(self) -> None:
        self.h.register(self.c)
        self.assertTrue(self.h.unregister("x"))
        self.assertFalse(self.h.unregister("x"))

    def test_filter_by_category(self) -> None:
        self.h.register(self.c)
        self.h.register(sth.HealthCheck(
            name="perf", category="performance",
            run=lambda: sth.CheckOutcome(ok=True),
        ))
        self.assertEqual(
            len(self.h.filter_by_category("memory")), 1,
        )


class TestRunAll(unittest.TestCase):
    def test_all_ok(self) -> None:
        h = sth.SelfTestHarness()
        h.register(sth.HealthCheck(
            name="a", category="memory",
            run=lambda: sth.CheckOutcome(ok=True),
        ))
        h.register(sth.HealthCheck(
            name="b", category="consistency",
            run=lambda: sth.CheckOutcome(ok=True),
        ))
        report = h.run_all()
        self.assertEqual(report.ok_count, 2)
        self.assertEqual(report.failed_count, 0)
        self.assertTrue(report.overall_ok)

    def test_failed_check_counted(self) -> None:
        h = sth.SelfTestHarness()
        h.register(sth.HealthCheck(
            name="bad", category="memory",
            run=lambda: sth.CheckOutcome(ok=False, note="boom"),
            severity="critical",
        ))
        report = h.run_all()
        self.assertEqual(report.failed_count, 1)
        self.assertEqual(report.critical_count, 1)
        self.assertFalse(report.overall_ok)

    def test_raising_check_counts_as_failure(self) -> None:
        def boom() -> sth.CheckOutcome:
            raise RuntimeError("x")

        h = sth.SelfTestHarness()
        h.register(sth.HealthCheck(
            name="raiser", category="memory", run=boom,
        ))
        report = h.run_all()
        self.assertEqual(report.failed_count, 1)
        self.assertIn("raised", report.results[0].note)

    def test_non_outcome_return_failure(self) -> None:
        h = sth.SelfTestHarness()
        h.register(sth.HealthCheck(
            name="weird", category="memory",
            run=lambda: "not an outcome",  # type: ignore[return-value]
        ))
        report = h.run_all()
        self.assertEqual(report.failed_count, 1)

    def test_category_filter(self) -> None:
        h = sth.SelfTestHarness()
        h.register(sth.HealthCheck(
            name="mem", category="memory",
            run=lambda: sth.CheckOutcome(ok=True),
        ))
        h.register(sth.HealthCheck(
            name="perf", category="performance",
            run=lambda: sth.CheckOutcome(ok=True),
        ))
        report = h.run_all(category="memory")
        self.assertEqual(len(report.results), 1)
        self.assertEqual(report.results[0].name, "mem")


class TestConsistencyHelper(unittest.TestCase):
    def test_predicate_true(self) -> None:
        c = sth.consistency_check(
            "x", predicate=lambda: 2 + 2 == 4,
        )
        result = c.run()
        self.assertTrue(result.ok)

    def test_predicate_false(self) -> None:
        c = sth.consistency_check(
            "x", predicate=lambda: False,
        )
        self.assertFalse(c.run().ok)

    def test_predicate_raise(self) -> None:
        def boom():
            raise RuntimeError("x")

        c = sth.consistency_check("x", predicate=boom)
        outcome = c.run()
        self.assertFalse(outcome.ok)
        self.assertIn("raised", outcome.note)


class TestMemoryNonzeroCheck(unittest.TestCase):
    def test_builtin_runs_without_crashing(self) -> None:
        c = sth.memory_nonzero_check(min_records=1_000_000)
        # No matter the state, the check should return an outcome
        result = c.run()
        self.assertIsInstance(result, sth.CheckOutcome)


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        h = sth.SelfTestHarness()
        h.register(sth.HealthCheck(
            name="a", category="memory",
            run=lambda: sth.CheckOutcome(ok=True),
        ))
        h.register(sth.HealthCheck(
            name="b", category="memory",
            run=lambda: sth.CheckOutcome(ok=True),
        ))
        h.register(sth.HealthCheck(
            name="c", category="performance",
            run=lambda: sth.CheckOutcome(ok=True),
        ))
        s = h.stats()
        self.assertEqual(s["registered_checks"], 3)
        self.assertEqual(s["by_category"]["memory"], 2)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        h = sth.SelfTestHarness()
        h.register(sth.HealthCheck(
            name="a", category="memory",
            run=lambda: sth.CheckOutcome(ok=True, note="fine"),
        ))
        d = h.run_all().as_dict()
        self.assertIn("results", d)
        self.assertIn("overall_ok", d)
        self.assertTrue(d["overall_ok"])


if __name__ == "__main__":
    unittest.main()
