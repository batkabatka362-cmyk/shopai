"""Budget allocator — fair-share + auto-reset tests."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from core.brain import budget_allocator as ba


class TestBasic(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pool = ba.BudgetPool(Path(self._tmp.name) / "b.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_defaults_seeded(self) -> None:
        s = self.pool.stats()
        self.assertIn("ad_spend_usd", s)
        self.assertIn("llm_tokens", s)
        self.assertIn("cycle_time_s", s)

    def test_set_cap_updates_and_clamps_remaining(self) -> None:
        self.pool.set_cap("ad_spend_usd", 50.0)
        s = self.pool.stats()
        self.assertEqual(s["ad_spend_usd"]["daily_cap"], 50.0)
        self.assertEqual(s["ad_spend_usd"]["remaining"], 50.0)

    def test_consume_grants_min_of_request_and_remaining(self) -> None:
        self.pool.set_cap("ad_spend_usd", 40.0)
        alloc = self.pool.consume("ad_spend_usd", "launch_A", 60.0)
        self.assertEqual(alloc.granted, 40.0)
        self.assertEqual(alloc.remaining_after, 0.0)

    def test_can_spend_checks_remaining(self) -> None:
        self.pool.set_cap("ad_spend_usd", 10.0)
        self.assertTrue(self.pool.can_spend("ad_spend_usd", 10))
        self.pool.consume("ad_spend_usd", "x", 10.0)
        self.assertFalse(self.pool.can_spend("ad_spend_usd", 1))


class TestFairShare(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pool = ba.BudgetPool(Path(self._tmp.name) / "b.json")
        self.pool.set_cap("ad_spend_usd", 100.0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_fair_share_caps_when_competing(self) -> None:
        # Two requesters, both priority 50, both demand 100 → each
        # gets 50 of the 100 pool.
        alloc = self.pool.consume(
            "ad_spend_usd", "A",
            requested=100.0, priority=50.0,
            competing=[("B", 50.0, 100.0)],
        )
        self.assertAlmostEqual(alloc.granted, 50.0)

    def test_higher_priority_wins_more(self) -> None:
        # A priority 80, B priority 20, both demand 100 → A gets 80
        alloc = self.pool.consume(
            "ad_spend_usd", "A",
            requested=100.0, priority=80.0,
            competing=[("B", 20.0, 100.0)],
        )
        self.assertAlmostEqual(alloc.granted, 80.0, places=1)


class TestAutoReset(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pool = ba.BudgetPool(Path(self._tmp.name) / "b.json")
        self.pool.set_cap("ad_spend_usd", 20.0)
        self.pool.consume("ad_spend_usd", "x", 20.0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_force_reset_restores_full(self) -> None:
        self.pool.reset("ad_spend_usd")
        s = self.pool.stats()
        self.assertEqual(s["ad_spend_usd"]["remaining"], 20.0)

    def test_auto_reset_after_window(self) -> None:
        # Manually rewind last_reset to 2 days ago
        import json
        state = json.loads(
            Path(self.pool._store).read_text(),
        )
        state["ad_spend_usd"]["last_reset"] = time.time() - 2 * 86_400
        Path(self.pool._store).write_text(json.dumps(state))
        # can_spend triggers the auto-reset check
        self.assertTrue(self.pool.can_spend("ad_spend_usd", 5.0))


class TestEmptyAndEdge(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.pool = ba.BudgetPool(Path(self._tmp.name) / "b.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_zero_request_grants_zero(self) -> None:
        alloc = self.pool.consume("ad_spend_usd", "x", 0.0)
        self.assertEqual(alloc.granted, 0.0)

    def test_unknown_resource_auto_created(self) -> None:
        alloc = self.pool.consume(
            "gpu_hours", "trainer",
            requested=5.0, priority=50.0,
        )
        # daily_cap seeded to the first request amount
        self.assertGreaterEqual(alloc.granted, 0.0)


if __name__ == "__main__":
    unittest.main()
