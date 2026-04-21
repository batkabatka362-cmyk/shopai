"""Tests for the per-IP webhook rate limiter (P0.2 security)."""
from __future__ import annotations

import os
import unittest

from core.webhooks.rate_limiter import (
    WebhookRateLimiter,
    _resolved_burst,
    _resolved_rate_rpm,
    get_webhook_rate_limiter,
    reset_webhook_rate_limiter_for_tests,
)


class _Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def tick(self, dt):
        self.t += dt


class _EnvSandbox:
    KEYS = (
        "SHOPAI_WEBHOOK_RATE_LIMIT_RPM",
        "SHOPAI_WEBHOOK_RATE_LIMIT_BURST",
    )

    def __enter__(self):
        self._orig = {
            k: os.environ.get(k) for k in self.KEYS
        }
        for k in self.KEYS:
            os.environ.pop(k, None)
        return self

    def __exit__(self, *a):
        for k, v in self._orig.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _build(**kw):
    defaults = dict(rate_rpm=60.0, burst=5)
    defaults.update(kw)
    return WebhookRateLimiter(**defaults)


class TestEnvResolution(unittest.TestCase):
    def test_default_rate(self):
        with _EnvSandbox():
            self.assertEqual(_resolved_rate_rpm(), 60.0)
            self.assertEqual(_resolved_burst(), 30)

    def test_env_override(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_WEBHOOK_RATE_LIMIT_RPM"
            ] = "120"
            os.environ[
                "SHOPAI_WEBHOOK_RATE_LIMIT_BURST"
            ] = "60"
            self.assertEqual(
                _resolved_rate_rpm(), 120.0,
            )
            self.assertEqual(_resolved_burst(), 60)

    def test_invalid_env_falls_back(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_WEBHOOK_RATE_LIMIT_RPM"
            ] = "not-a-number"
            self.assertEqual(_resolved_rate_rpm(), 60.0)

    def test_negative_env_falls_back(self):
        with _EnvSandbox():
            os.environ[
                "SHOPAI_WEBHOOK_RATE_LIMIT_RPM"
            ] = "-5"
            self.assertEqual(_resolved_rate_rpm(), 60.0)


class TestValidation(unittest.TestCase):
    def test_zero_rate_raises(self):
        with self.assertRaises(ValueError):
            WebhookRateLimiter(rate_rpm=0, burst=5)

    def test_zero_burst_raises(self):
        with self.assertRaises(ValueError):
            WebhookRateLimiter(rate_rpm=60, burst=0)


class TestBucket(unittest.TestCase):
    def test_first_request_allowed(self):
        clock = _Clock()
        rl = _build(now_fn=clock)
        d = rl.consume("1.2.3.4")
        self.assertTrue(d.allowed)
        self.assertAlmostEqual(d.tokens_remaining, 4.0)

    def test_burst_exhausts(self):
        clock = _Clock()
        rl = _build(now_fn=clock)
        for _ in range(5):
            rl.consume("1.2.3.4")
        d = rl.consume("1.2.3.4")
        self.assertFalse(d.allowed)
        self.assertGreater(d.retry_after_s, 0)

    def test_refill_over_time(self):
        clock = _Clock()
        rl = _build(now_fn=clock)
        # Drain all 5 tokens
        for _ in range(5):
            rl.consume("1.2.3.4")
        self.assertFalse(rl.consume("1.2.3.4").allowed)
        # 60s later → 1 token (rate is 1 per sec)
        clock.tick(60)
        d = rl.consume("1.2.3.4")
        self.assertTrue(d.allowed)

    def test_separate_ips_separate_buckets(self):
        clock = _Clock()
        rl = _build(now_fn=clock)
        for _ in range(5):
            rl.consume("1.1.1.1")
        # IP A exhausted, IP B fresh
        self.assertFalse(rl.consume("1.1.1.1").allowed)
        self.assertTrue(rl.consume("2.2.2.2").allowed)

    def test_blank_ip_uses_unknown_bucket(self):
        clock = _Clock()
        rl = _build(now_fn=clock)
        d = rl.consume("")
        self.assertTrue(d.allowed)
        self.assertEqual(
            list(rl._buckets.keys()), ["_unknown"],
        )

    def test_zero_charge_no_op(self):
        rl = _build()
        d = rl.consume("1.2.3.4", n=0)
        self.assertTrue(d.allowed)
        self.assertIn("zero", d.reason)


class TestEviction(unittest.TestCase):
    def test_idle_buckets_evicted(self):
        clock = _Clock()
        rl = _build(now_fn=clock, idle_evict_s=10)
        rl.consume("1.1.1.1")
        rl.consume("2.2.2.2")
        clock.tick(15)
        # Touching 3.3.3.3 triggers GC of the two idle ones
        rl.consume("3.3.3.3")
        keys = sorted(rl._buckets.keys())
        self.assertEqual(keys, ["3.3.3.3"])

    def test_eviction_off_when_zero(self):
        clock = _Clock()
        rl = _build(now_fn=clock, idle_evict_s=0)
        rl.consume("1.1.1.1")
        clock.tick(10_000)
        rl.consume("2.2.2.2")
        self.assertEqual(len(rl._buckets), 2)


class TestStats(unittest.TestCase):
    def test_consumed_and_rejected_counters(self):
        clock = _Clock()
        rl = _build(now_fn=clock)
        for _ in range(5):
            rl.consume("1.1.1.1")
        rl.consume("1.1.1.1")  # rejected
        s = rl.stats()
        self.assertEqual(s["consumed_total"], 5)
        self.assertEqual(s["rejected_total"], 1)
        self.assertEqual(s["active_buckets"], 1)
        self.assertEqual(s["burst"], 5)

    def test_reset_clears(self):
        rl = _build()
        rl.consume("1.1.1.1")
        rl.reset()
        self.assertEqual(rl.stats()["active_buckets"], 0)


class TestSingleton(unittest.TestCase):
    def test_singleton_returns_same(self):
        with _EnvSandbox():
            reset_webhook_rate_limiter_for_tests()
            a = get_webhook_rate_limiter()
            b = get_webhook_rate_limiter()
            self.assertIs(a, b)
            reset_webhook_rate_limiter_for_tests()


class TestMcpTool(unittest.TestCase):
    def test_registered_and_returns_stats(self):
        from mcp_server.tools import (
            ToolCall, build_default_registry,
        )
        with _EnvSandbox():
            reset_webhook_rate_limiter_for_tests()
            reg = build_default_registry()
            res = reg.call(ToolCall(
                tool="webhook_rate_limit_status",
            ))
        self.assertTrue(res.ok)
        for key in (
            "active_buckets", "consumed_total",
            "rejected_total", "rate_rpm", "burst",
        ):
            self.assertIn(key, res.content)
        reset_webhook_rate_limiter_for_tests()


if __name__ == "__main__":
    unittest.main()
