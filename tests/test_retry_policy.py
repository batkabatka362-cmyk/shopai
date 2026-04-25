"""Retry policy tests."""
from __future__ import annotations

import time
import unittest

from core.system import retry_policy as rp


class TestCallSuccess(unittest.TestCase):
    def test_first_try_succeeds(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register("ok", max_attempts=3, base_delay_s=0.001)
        calls = {"n": 0}
        def fn():
            calls["n"] += 1
            return "ok"
        self.assertEqual(spec.call(fn), "ok")
        self.assertEqual(calls["n"], 1)


class TestRetriesThenSuccess(unittest.TestCase):
    def test_retries_until_success(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register("flap", max_attempts=3, base_delay_s=0.001,
                             jitter_s=0)
        attempts = {"n": 0}
        def fn():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("transient")
            return "done"
        self.assertEqual(spec.call(fn), "done")
        self.assertEqual(attempts["n"], 3)


class TestExhausted(unittest.TestCase):
    def test_exhausted_raises_last_exception(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register("bad", max_attempts=2, base_delay_s=0.001,
                             jitter_s=0)
        def fn():
            raise RuntimeError("nope")
        with self.assertRaises(RuntimeError):
            spec.call(fn)


class TestCircuitBreaker(unittest.TestCase):
    def test_opens_after_threshold(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register(
            "b", max_attempts=1, base_delay_s=0.001,
            failure_threshold=3, failure_window_s=60,
        )
        def fn():
            raise RuntimeError("boom")
        for _ in range(3):
            try:
                spec.call(fn)
            except RuntimeError:
                pass
        self.assertTrue(spec.is_open())

    def test_open_circuit_refuses_calls(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register(
            "b", max_attempts=1,
            failure_threshold=1, failure_window_s=60,
        )
        def fn():
            raise RuntimeError("boom")
        try:
            spec.call(fn)
        except RuntimeError:
            pass
        self.assertTrue(spec.is_open())
        with self.assertRaises(rp.BreakerOpen):
            spec.call(lambda: "ok")

    def test_reset_closes_circuit(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register(
            "b", max_attempts=1,
            failure_threshold=1, failure_window_s=60,
        )
        try:
            spec.call(lambda: (_ for _ in ()).throw(
                RuntimeError("x"),
            ))
        except RuntimeError:
            pass
        self.assertTrue(spec.is_open())
        spec.reset()
        self.assertFalse(spec.is_open())

    def test_half_open_single_probe_success(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register(
            "b", max_attempts=1, base_delay_s=0.001,
            failure_threshold=1, failure_window_s=60,
            reset_after_s=0.05,
        )
        try:
            spec.call(lambda: (_ for _ in ()).throw(
                RuntimeError("x"),
            ))
        except RuntimeError:
            pass
        self.assertTrue(spec.is_open())
        time.sleep(0.1)
        # In half-open, one probe decides. Success closes the circuit.
        self.assertEqual(spec.call(lambda: "recovered"), "recovered")
        self.assertFalse(spec.is_open())


class TestDelay(unittest.TestCase):
    def test_delay_bounded_by_max(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register(
            "d", base_delay_s=1.0, max_delay_s=2.0, jitter_s=0,
        )
        self.assertLessEqual(spec._delay(10), 2.5)


class TestOnAttempt(unittest.TestCase):
    def test_on_attempt_fires_per_failure(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.register(
            "c", max_attempts=3, base_delay_s=0.001, jitter_s=0,
        )
        seen: list[tuple[int, str]] = []
        def fn():
            raise RuntimeError("bad")
        try:
            spec.call(
                fn,
                on_attempt=lambda n, e: seen.append((n, str(e))),
            )
        except RuntimeError:
            pass
        self.assertEqual(len(seen), 3)


class TestDecorator(unittest.TestCase):
    def test_with_retry_wraps(self) -> None:
        # Use short-hand decorator
        calls = {"n": 0}
        @rp.with_retry("dec")
        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("once")
            return "ok"
        # Before calling decorator, reduce delay
        rp.registry().get("dec").max_attempts = 3
        rp.registry().get("dec").base_delay_s = 0.001
        rp.registry().get("dec").jitter_s = 0
        self.assertEqual(flaky(), "ok")


class TestRegistry(unittest.TestCase):
    def test_get_auto_registers(self) -> None:
        reg = rp.RetryRegistry()
        spec = reg.get("brand_new")
        self.assertEqual(spec.name, "brand_new")

    def test_stats_returns_dict(self) -> None:
        reg = rp.RetryRegistry()
        reg.register("s")
        stats = reg.stats()
        self.assertIn("s", stats)
        self.assertEqual(stats["s"]["state"], "closed")


if __name__ == "__main__":
    unittest.main()
