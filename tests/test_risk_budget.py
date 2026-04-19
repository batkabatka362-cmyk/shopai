"""Risk budget tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import risk_budget as rb


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.b = rb.RiskBudget(Path(self._tmp.name) / "r.db")

    def tearDown(self) -> None:
        self.b.close()
        self._tmp.cleanup()


class TestConfig(unittest.TestCase):
    def test_bad_ttl_raises(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        with self.assertRaises(ValueError):
            rb.RiskBudget(
                Path(tmp.name) / "x.db", reservation_ttl_s=0,
            )
        tmp.cleanup()


class TestCap(TestSetup):
    def test_set_and_read(self) -> None:
        self.b.set_cap("ads", 10.0)
        self.assertEqual(self.b.cap("ads"), 10.0)

    def test_blank_category_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.set_cap("", 10)

    def test_negative_cap_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.set_cap("ads", -1)


class TestReserveCommit(TestSetup):
    def test_reserve_within_cap(self) -> None:
        self.b.set_cap("ads", 10.0)
        r = self.b.reserve("ads", 4.0, reason="test")
        self.assertEqual(r.units, 4.0)
        self.assertEqual(
            self.b.status("ads").reserved_units, 4.0,
        )

    def test_over_cap_raises(self) -> None:
        self.b.set_cap("ads", 5.0)
        self.b.reserve("ads", 3.0)
        with self.assertRaises(rb.RiskBudgetExceeded):
            self.b.reserve("ads", 3.0)

    def test_commit_with_actual(self) -> None:
        self.b.set_cap("ads", 10.0)
        r = self.b.reserve("ads", 5.0)
        self.b.commit(r.id, actual_units=4.0)
        s = self.b.status("ads")
        self.assertEqual(s.spent_units, 4.0)
        self.assertEqual(s.reserved_units, 0.0)

    def test_commit_defaults_to_reserved(self) -> None:
        self.b.set_cap("ads", 10.0)
        r = self.b.reserve("ads", 3.0)
        self.b.commit(r.id)
        self.assertEqual(
            self.b.status("ads").spent_units, 3.0,
        )

    def test_release_undoes_reservation(self) -> None:
        self.b.set_cap("ads", 10.0)
        r = self.b.reserve("ads", 5.0)
        self.b.release(r.id)
        self.assertEqual(
            self.b.status("ads").reserved_units, 0.0,
        )

    def test_commit_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.commit("nope")

    def test_release_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.release("nope")

    def test_double_commit_raises(self) -> None:
        self.b.set_cap("ads", 10.0)
        r = self.b.reserve("ads", 3.0)
        self.b.commit(r.id)
        with self.assertRaises(ValueError):
            self.b.commit(r.id)

    def test_negative_units_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.b.reserve("ads", -1)
        with self.assertRaises(ValueError):
            self.b.spend("ads", 0)


class TestSpend(TestSetup):
    def test_direct_spend(self) -> None:
        self.b.set_cap("ads", 5.0)
        self.b.spend("ads", 2.0, reason="test")
        self.assertEqual(
            self.b.status("ads").spent_units, 2.0,
        )

    def test_over_cap_raises(self) -> None:
        self.b.set_cap("ads", 5.0)
        self.b.spend("ads", 4.0)
        with self.assertRaises(rb.RiskBudgetExceeded):
            self.b.spend("ads", 2.0)


class TestUnlimited(TestSetup):
    def test_no_cap_allows_everything(self) -> None:
        # No cap set → spend freely
        self.b.spend("unbounded", 999.0)
        self.assertEqual(
            self.b.status("unbounded").spent_units, 999.0,
        )


class TestHousekeep(unittest.TestCase):
    def test_stale_reservation_reaped(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        b = rb.RiskBudget(
            Path(tmp.name) / "r.db",
            reservation_ttl_s=0.01,
        )
        b.set_cap("ads", 10.0)
        r = b.reserve("ads", 5.0)
        time.sleep(0.05)
        released = b.housekeep()
        self.assertEqual(released, 1)
        with self.assertRaises(ValueError):
            b.commit(r.id)
        b.close()
        tmp.cleanup()


class TestOverview(TestSetup):
    def test_lists_all_caps(self) -> None:
        self.b.set_cap("ads", 10.0)
        self.b.set_cap("refunds", 3.0)
        ov = self.b.overview()
        cats = [s.category for s in ov]
        self.assertIn("ads", cats)
        self.assertIn("refunds", cats)


class TestStats(TestSetup):
    def test_stats_shape(self) -> None:
        self.b.set_cap("ads", 10.0)
        self.b.reserve("ads", 3.0)
        s = self.b.stats()
        self.assertEqual(s["active_reservations"], 1)
        self.assertEqual(s["caps_registered"], 1)


class TestDict(TestSetup):
    def test_reservation_serialises(self) -> None:
        self.b.set_cap("ads", 10.0)
        r = self.b.reserve("ads", 3.0, reason="test")
        d = r.as_dict()
        self.assertEqual(d["units"], 3.0)
        self.assertEqual(d["reason"], "test")

    def test_status_serialises(self) -> None:
        self.b.set_cap("ads", 10.0)
        d = self.b.status("ads").as_dict()
        self.assertIn("remaining_units", d)


if __name__ == "__main__":
    unittest.main()
