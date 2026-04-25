"""Rate limiter tests."""
from __future__ import annotations

import time
import unittest

from core.system import rate_limiter as rl


class TestTokenBucket(unittest.TestCase):
    def test_fills_to_capacity_initially(self) -> None:
        b = rl.TokenBucket(rate_per_sec=1.0, capacity=5.0)
        self.assertTrue(b.try_acquire(5))
        self.assertFalse(b.try_acquire(1))

    def test_refills_over_time(self) -> None:
        b = rl.TokenBucket(rate_per_sec=100.0, capacity=1.0)
        self.assertTrue(b.try_acquire(1))
        self.assertFalse(b.try_acquire(1))
        # Wait 50ms → ~5 tokens refilled → 1 acquire succeeds
        time.sleep(0.05)
        self.assertTrue(b.try_acquire(1))

    def test_acquire_blocks_until_granted(self) -> None:
        b = rl.TokenBucket(rate_per_sec=50.0, capacity=1.0)
        b.try_acquire(1)
        start = time.monotonic()
        granted = b.acquire(1, timeout=1.0)
        elapsed = time.monotonic() - start
        self.assertTrue(granted)
        self.assertGreater(elapsed, 0.005)

    def test_acquire_timeout_returns_false(self) -> None:
        b = rl.TokenBucket(rate_per_sec=0.01, capacity=1.0)
        b.try_acquire(1)
        self.assertFalse(b.acquire(1, timeout=0.05))

    def test_zero_rate_raises(self) -> None:
        with self.assertRaises(ValueError):
            rl.TokenBucket(0)


class TestSlidingWindow(unittest.TestCase):
    def test_limit_enforced(self) -> None:
        w = rl.SlidingWindow(limit=3, window_s=10)
        for _ in range(3):
            self.assertTrue(w.allow())
        self.assertFalse(w.allow())

    def test_window_expiration(self) -> None:
        w = rl.SlidingWindow(limit=1, window_s=0.05)
        self.assertTrue(w.allow())
        self.assertFalse(w.allow())
        time.sleep(0.1)
        self.assertTrue(w.allow())

    def test_count_shrinks_with_time(self) -> None:
        w = rl.SlidingWindow(limit=10, window_s=0.05)
        for _ in range(5):
            w.allow()
        self.assertEqual(w.count(), 5)
        time.sleep(0.1)
        self.assertEqual(w.count(), 0)


class TestCostBudget(unittest.TestCase):
    def test_allows_until_cap(self) -> None:
        b = rl.CostBudget(cap_per_window=1.0, window_s=10)
        self.assertTrue(b.allow(0.4))
        self.assertTrue(b.allow(0.5))
        self.assertFalse(b.allow(0.2))

    def test_negative_cost_rejected(self) -> None:
        b = rl.CostBudget(cap_per_window=1.0)
        self.assertFalse(b.allow(-0.1))

    def test_remaining_and_spent(self) -> None:
        b = rl.CostBudget(cap_per_window=1.0, window_s=10)
        b.allow(0.3)
        self.assertAlmostEqual(b.spent(), 0.3, places=4)
        self.assertAlmostEqual(b.remaining(), 0.7, places=4)


class TestRegistry(unittest.TestCase):
    def test_defaults_registered(self) -> None:
        reg = rl.LimiterRegistry()
        for name in ("shopify_rest", "meta_ads", "groq", "gemini",
                      "deepseek"):
            self.assertIsNotNone(reg.get(name).bucket)

    def test_unknown_name_auto_registered(self) -> None:
        reg = rl.LimiterRegistry()
        spec = reg.get("brand_new")
        self.assertIsNotNone(spec.bucket)

    def test_custom_register_with_budget(self) -> None:
        reg = rl.LimiterRegistry()
        spec = reg.register(
            "custom", rate_per_sec=5.0, capacity=5.0,
            budget_cap=10.0, budget_window_s=3600,
        )
        self.assertTrue(spec.can_call())
        self.assertTrue(spec.budget.allow(2.0))

    def test_stats_reports_state(self) -> None:
        reg = rl.LimiterRegistry()
        reg.register(
            "s", rate_per_sec=1.0, sliding_limit=3,
            sliding_window_s=10, budget_cap=1.0,
        )
        reg.get("s").can_call(cost=0.1)
        stats = reg.stats()["s"]
        self.assertIsNotNone(stats["tokens_available"])
        self.assertIsNotNone(stats["window_count"])
        self.assertIsNotNone(stats["budget_spent"])


class TestLimiterSpec(unittest.TestCase):
    def test_can_call_combines_all(self) -> None:
        spec = rl.LimiterSpec(
            bucket=rl.TokenBucket(5.0, 5.0),
            window=rl.SlidingWindow(10, 10),
            budget=rl.CostBudget(1.0),
        )
        self.assertTrue(spec.can_call(cost=0.2))

    def test_window_exhausted_blocks_can_call(self) -> None:
        spec = rl.LimiterSpec(window=rl.SlidingWindow(1, 10))
        self.assertTrue(spec.can_call())
        self.assertFalse(spec.can_call())


class TestShortcut(unittest.TestCase):
    def test_rate_limit_returns_spec(self) -> None:
        spec = rl.rate_limit("shopify_rest")
        self.assertIsNotNone(spec.bucket)


if __name__ == "__main__":
    unittest.main()
