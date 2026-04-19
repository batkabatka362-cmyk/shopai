"""Compute budget tests."""
from __future__ import annotations

import unittest

from core.brain import compute_budget as cb


class TestBudgetSpec(unittest.TestCase):
    def test_blank_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            cb.BudgetSpec(
                kind="", max_per_cycle=1.0, warn_at=0.5,
            )

    def test_bad_cap_raises(self) -> None:
        with self.assertRaises(ValueError):
            cb.BudgetSpec(
                kind="k", max_per_cycle=0, warn_at=0.5,
            )

    def test_bad_warn_raises(self) -> None:
        with self.assertRaises(ValueError):
            cb.BudgetSpec(
                kind="k", max_per_cycle=1.0, warn_at=1.5,
            )


class TestBegin(unittest.TestCase):
    def setUp(self) -> None:
        self.budget = cb.ComputeBudget()

    def test_begin_sets_cycle(self) -> None:
        self.budget.begin_cycle("c1")
        self.assertEqual(
            self.budget.stats()["current_cycle"], "c1",
        )

    def test_blank_cycle_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.budget.begin_cycle("")

    def test_double_open_raises(self) -> None:
        self.budget.begin_cycle("c1")
        with self.assertRaises(ValueError):
            self.budget.begin_cycle("c2")

    def test_end_without_begin_returns_none(self) -> None:
        self.assertIsNone(self.budget.end_cycle())


class TestSpend(unittest.TestCase):
    def setUp(self) -> None:
        self.budget = cb.ComputeBudget()
        self.budget.register_budget(cb.BudgetSpec(
            kind="usd",
            max_per_cycle=0.10,
            warn_at=0.8,
        ))
        self.budget.begin_cycle("c1")

    def test_blank_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.budget.spend("", 0.01)

    def test_negative_amount_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.budget.spend("usd", -1)

    def test_spend_accumulates(self) -> None:
        self.budget.spend("usd", 0.01)
        self.budget.spend("usd", 0.02)
        self.assertAlmostEqual(
            self.budget.current_spend()["usd"], 0.03,
        )

    def test_under_budget_no_alert(self) -> None:
        alert = self.budget.spend("usd", 0.05)
        self.assertIsNone(alert)

    def test_warn_alert_fires_once(self) -> None:
        # 80% of 0.10 = 0.08
        a1 = self.budget.spend("usd", 0.08)
        self.assertIsNotNone(a1)
        self.assertEqual(a1.level, "warn")
        a2 = self.budget.spend("usd", 0.005)
        # Still under cap, already warned → no new alert
        self.assertIsNone(a2)

    def test_over_budget_alert(self) -> None:
        alert = self.budget.spend("usd", 0.15)
        self.assertIsNotNone(alert)
        self.assertEqual(alert.level, "over")

    def test_unknown_kind_no_budget(self) -> None:
        # Spending on unregistered kind accumulates but no alert
        self.budget.spend("latency", 1000.0)
        self.assertIsNone(
            self.budget.spend("latency", 9999.0),
        )


class TestCheck(unittest.TestCase):
    def test_over_raises(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=1.0, warn_at=0.5,
        ))
        budget.begin_cycle("c")
        budget.spend("k", 2.0)
        with self.assertRaises(cb.OverBudgetError):
            budget.check("k")

    def test_under_ok(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=1.0, warn_at=0.5,
        ))
        budget.begin_cycle("c")
        budget.spend("k", 0.5)
        budget.check("k")  # no raise

    def test_outside_cycle_noop(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=1.0, warn_at=0.5,
        ))
        # No begin_cycle — check does nothing
        budget.check("k")


class TestRemaining(unittest.TestCase):
    def test_remaining(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=10.0, warn_at=0.8,
        ))
        budget.begin_cycle("c")
        budget.spend("k", 3.0)
        self.assertAlmostEqual(budget.remaining("k"), 7.0)

    def test_unknown_infinite(self) -> None:
        budget = cb.ComputeBudget()
        self.assertEqual(
            budget.remaining("never"), float("inf"),
        )

    def test_over_returns_zero(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=1.0, warn_at=0.5,
        ))
        budget.begin_cycle("c")
        budget.spend("k", 5.0)
        self.assertEqual(budget.remaining("k"), 0.0)


class TestCallback(unittest.TestCase):
    def test_callback_fires(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=1.0, warn_at=0.5,
        ))
        received: list[cb.BudgetAlert] = []
        budget.set_alert_callback(lambda a: received.append(a))
        budget.begin_cycle("c")
        budget.spend("k", 2.0)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].level, "over")


class TestCycleArchive(unittest.TestCase):
    def test_end_archives(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=10.0, warn_at=0.8,
        ))
        budget.begin_cycle("c1")
        budget.spend("k", 3.0)
        report = budget.end_cycle()
        self.assertEqual(report.cycle_id, "c1")
        self.assertAlmostEqual(
            report.spent_by_kind["k"], 3.0,
        )

    def test_archive_limit(self) -> None:
        budget = cb.ComputeBudget()
        for i in range(5):
            budget.begin_cycle(f"c{i}")
            budget.end_cycle()
        self.assertEqual(
            budget.stats()["archived_cycles"], 5,
        )


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=1.0, warn_at=0.5,
        ))
        s = budget.stats()
        self.assertIn("budgets", s)
        self.assertIn("k", s["budgets"])


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        budget = cb.ComputeBudget()
        budget.begin_cycle("c")
        budget.end_cycle()
        self.assertEqual(budget.reset(), 1)


class TestDict(unittest.TestCase):
    def test_alert_serialises(self) -> None:
        budget = cb.ComputeBudget()
        budget.register_budget(cb.BudgetSpec(
            kind="k", max_per_cycle=1.0, warn_at=0.5,
        ))
        budget.begin_cycle("c")
        alert = budget.spend("k", 2.0)
        d = alert.as_dict()
        self.assertEqual(d["level"], "over")

    def test_report_serialises(self) -> None:
        budget = cb.ComputeBudget()
        budget.begin_cycle("c")
        report = budget.end_cycle()
        d = report.as_dict()
        self.assertIn("spent_by_kind", d)


if __name__ == "__main__":
    unittest.main()
