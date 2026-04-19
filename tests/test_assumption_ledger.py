"""Assumption ledger tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import assumption_ledger as al


class TestDataclass(unittest.TestCase):
    def test_bad_status_raises(self) -> None:
        with self.assertRaises(ValueError):
            al.Assumption(
                id="x", statement="s",
                related_decision_id="", kpi="",
                expected_value=None, tolerance=0.0,
                status="weird",  # type: ignore[arg-type]
                created_ts=0.0,
            )

    def test_bad_tolerance_raises(self) -> None:
        with self.assertRaises(ValueError):
            al.Assumption(
                id="x", statement="s",
                related_decision_id="", kpi="",
                expected_value=None, tolerance=-1.0,
                status="pending",
                created_ts=0.0,
            )


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = al.AssumptionLedger(
            Path(self._tmp.name) / "a.db",
        )

    def tearDown(self) -> None:
        self.ledger.close()
        self._tmp.cleanup()


class TestAssume(TestSetup):
    def test_happy_path(self) -> None:
        a = self.ledger.assume(
            statement="CPM will stay under $25",
            related_decision_id="d1",
            kpi="cpm",
            expected_value=25.0,
            tolerance=5.0,
        )
        self.assertEqual(a.status, "pending")

    def test_blank_statement_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.ledger.assume(statement="")

    def test_bad_tolerance_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.ledger.assume(
                statement="s", tolerance=-0.1,
            )


class TestValidate(TestSetup):
    def setUp(self) -> None:
        super().setUp()
        self.a = self.ledger.assume(
            statement="ROAS ≈ 2.0",
            related_decision_id="d1",
            kpi="roas",
            expected_value=2.0,
            tolerance=0.3,
        )

    def test_validate_within_band(self) -> None:
        r = self.ledger.validate(self.a.id, 2.1)
        self.assertEqual(r.status, "validated")

    def test_validate_outside_band(self) -> None:
        r = self.ledger.validate(self.a.id, 1.0)
        self.assertEqual(r.status, "violated")

    def test_no_expected_is_validated(self) -> None:
        b = self.ledger.assume(statement="ad launches")
        r = self.ledger.validate(b.id, 0.0)
        self.assertEqual(r.status, "validated")

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.ledger.validate("no", 1.0)

    def test_cannot_double_validate(self) -> None:
        self.ledger.validate(self.a.id, 2.0)
        with self.assertRaises(ValueError):
            self.ledger.validate(self.a.id, 2.0)


class TestAbandon(TestSetup):
    def test_abandon(self) -> None:
        a = self.ledger.assume(statement="s")
        r = self.ledger.abandon(a.id, note="obsolete")
        self.assertEqual(r.status, "abandoned")
        self.assertEqual(r.note, "obsolete")

    def test_cannot_abandon_resolved(self) -> None:
        a = self.ledger.assume(statement="s")
        self.ledger.validate(a.id, 0.0)
        with self.assertRaises(ValueError):
            self.ledger.abandon(a.id)


class TestQueries(TestSetup):
    def test_by_status(self) -> None:
        a1 = self.ledger.assume(
            statement="s1", expected_value=1.0, tolerance=0.1,
        )
        a2 = self.ledger.assume(
            statement="s2", expected_value=1.0, tolerance=0.1,
        )
        self.ledger.validate(a1.id, 1.0)
        self.ledger.validate(a2.id, 5.0)
        self.assertEqual(
            len(self.ledger.by_status("validated")), 1,
        )
        self.assertEqual(
            len(self.ledger.by_status("violated")), 1,
        )

    def test_by_decision(self) -> None:
        self.ledger.assume(
            statement="s1", related_decision_id="d1",
        )
        self.ledger.assume(
            statement="s2", related_decision_id="d1",
        )
        self.ledger.assume(
            statement="s3", related_decision_id="d2",
        )
        self.assertEqual(
            len(self.ledger.by_decision("d1")), 2,
        )

    def test_violation_rate(self) -> None:
        a1 = self.ledger.assume(
            statement="s1", expected_value=1.0, tolerance=0.1,
        )
        a2 = self.ledger.assume(
            statement="s2", expected_value=1.0, tolerance=0.1,
        )
        self.ledger.validate(a1.id, 1.0)
        self.ledger.validate(a2.id, 5.0)
        self.assertEqual(self.ledger.violation_rate(), 0.5)


class TestStats(TestSetup):
    def test_stats_shape(self) -> None:
        a = self.ledger.assume(
            statement="s", expected_value=1.0, tolerance=0.1,
        )
        self.ledger.validate(a.id, 1.0)
        s = self.ledger.stats()
        self.assertEqual(s["total"], 1)
        self.assertIn("by_status", s)
        self.assertIn("violation_rate", s)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "a.db"
        first = al.AssumptionLedger(path)
        a = first.assume(
            statement="x", expected_value=1.0, tolerance=0.1,
        )
        first.validate(a.id, 1.05)
        first.close()
        second = al.AssumptionLedger(path)
        r = second.get(a.id)
        self.assertEqual(r.status, "validated")
        self.assertEqual(r.observed_value, 1.05)
        second.close()
        tmp.cleanup()


class TestDict(TestSetup):
    def test_serialises(self) -> None:
        a = self.ledger.assume(
            statement="x", expected_value=1.0, tolerance=0.1,
        )
        d = a.as_dict()
        self.assertIn("statement", d)
        self.assertEqual(d["status"], "pending")


if __name__ == "__main__":
    unittest.main()
