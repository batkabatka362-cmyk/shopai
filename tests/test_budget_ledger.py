"""Budget ledger tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import budget_ledger as bl


class TestSetup(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.led = bl.BudgetLedger(Path(self._tmp.name) / "b.db")

    def tearDown(self) -> None:
        self.led.close()
        self._tmp.cleanup()


class TestSetCap(TestSetup):
    def test_set_and_read(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        self.assertEqual(self.led.cap("ads", "day"), 20.0)

    def test_bad_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.led.set_cap("ads", "annual", 100)

    def test_negative_cap_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.led.set_cap("ads", "day", -1)


class TestSpend(TestSetup):
    def test_simple_spend_fits(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        self.led.spend("ads", 10.0)
        status = self.led.status("ads", "day")
        self.assertEqual(status.spent_usd, 10.0)
        self.assertEqual(status.remaining_usd, 10.0)

    def test_over_spend_raises(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        self.led.spend("ads", 15.0)
        with self.assertRaises(bl.BudgetExceeded):
            self.led.spend("ads", 10.0)

    def test_zero_spend_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.led.spend("ads", 0)


class TestReserveCommit(TestSetup):
    def test_reserve_holds_amount(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        r = self.led.reserve("ads", 15.0)
        status = self.led.status("ads", "day")
        self.assertEqual(status.reserved_usd, 15.0)
        self.assertEqual(status.remaining_usd, 5.0)
        # Another reservation that exceeds remaining is rejected
        with self.assertRaises(bl.BudgetExceeded):
            self.led.reserve("ads", 10.0)
        self.assertEqual(r.amount, 15.0)

    def test_commit_finalises(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        r = self.led.reserve("ads", 15.0)
        self.led.commit(r.id, actual_amount=12.0)
        status = self.led.status("ads", "day")
        self.assertEqual(status.spent_usd, 12.0)
        self.assertEqual(status.reserved_usd, 0.0)

    def test_commit_with_no_actual_uses_reserved(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        r = self.led.reserve("ads", 10.0)
        self.led.commit(r.id)
        self.assertEqual(
            self.led.status("ads", "day").spent_usd, 10.0,
        )

    def test_release_undoes_reservation(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        r = self.led.reserve("ads", 15.0)
        self.led.release(r.id)
        self.assertEqual(
            self.led.status("ads", "day").reserved_usd, 0.0,
        )

    def test_commit_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.led.commit("not-a-real-id")

    def test_release_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.led.release("not-a-real-id")

    def test_double_commit_raises(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        r = self.led.reserve("ads", 5.0)
        self.led.commit(r.id)
        with self.assertRaises(ValueError):
            self.led.commit(r.id)


class TestMultiWindow(TestSetup):
    def test_smallest_window_wins(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        self.led.set_cap("ads", "week", 100.0)
        self.led.spend("ads", 18.0)
        # Day cap blocks even though week has plenty
        with self.assertRaises(bl.BudgetExceeded):
            self.led.spend("ads", 5.0)


class TestOverview(TestSetup):
    def test_overview_lists_all_caps(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        self.led.set_cap("ads", "week", 100.0)
        self.led.set_cap("refunds", "day", 50.0)
        ov = self.led.overview()
        keys = [(s.category, s.window) for s in ov]
        self.assertIn(("ads", "day"), keys)
        self.assertIn(("refunds", "day"), keys)
        self.assertEqual(len(ov), 3)


class TestHousekeep(TestSetup):
    def test_stale_reservation_released(self) -> None:
        led = bl.BudgetLedger(
            Path(self._tmp.name) / "b2.db",
            reservation_ttl_s=0.01,  # 10 ms TTL
        )
        led.set_cap("ads", "day", 20.0)
        r = led.reserve("ads", 5.0)
        time.sleep(0.05)
        released = led.housekeep()
        self.assertEqual(released, 1)
        # Subsequent commit fails because it was released.
        with self.assertRaises(ValueError):
            led.commit(r.id)
        led.close()


class TestStats(TestSetup):
    def test_stats(self) -> None:
        self.led.set_cap("ads", "day", 10.0)
        r = self.led.reserve("ads", 3.0)
        self.led.spend("ads", 2.0)
        s = self.led.stats()
        self.assertEqual(s["active_reservations"], 1)
        self.assertGreaterEqual(s["active_entries"], 2)
        self.assertEqual(s["caps_registered"], 1)
        # Silence the linter about the reservation id
        self.assertTrue(r.id)


class TestDict(TestSetup):
    def test_status_as_dict(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        self.led.spend("ads", 5.0)
        d = self.led.status("ads", "day").as_dict()
        self.assertEqual(d["cap_usd"], 20.0)
        self.assertEqual(d["spent_usd"], 5.0)

    def test_reservation_as_dict(self) -> None:
        self.led.set_cap("ads", "day", 20.0)
        r = self.led.reserve("ads", 5.0)
        d = r.as_dict()
        self.assertEqual(d["amount"], 5.0)


if __name__ == "__main__":
    unittest.main()
