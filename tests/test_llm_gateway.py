"""LLM gateway tests.

The gateway delegates to ``core.adapters.router`` which may or may not
have real credentials in a test environment. These tests exercise the
pure orchestration logic — cost estimation, stats tracking, error
paths, cycle_block guard — without requiring a live network.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core import llm_gateway as gw


class TestCostEstimator(unittest.TestCase):
    def test_unknown_adapter_zero_cost(self) -> None:
        self.assertEqual(gw._estimate_cost("nobody", 1000, 1000), 0.0)

    def test_known_adapter_nonzero(self) -> None:
        c = gw._estimate_cost("gemini", 1_000_000, 1_000_000)
        self.assertGreater(c, 0.0)
        # Per rate table: 0.15 + 0.60 = 0.75
        self.assertAlmostEqual(c, 0.75, places=4)

    def test_zero_tokens_zero_cost(self) -> None:
        self.assertEqual(gw._estimate_cost("groq", 0, 0), 0.0)


class TestCycleBlock(unittest.TestCase):
    def test_cycle_block_refuses(self) -> None:
        r = gw.ask("anything", purpose="cycle_block")
        self.assertFalse(r.ok)
        self.assertIn("cycle_block", r.error)

    def test_empty_prompt_refused(self) -> None:
        r = gw.ask("")
        self.assertFalse(r.ok)


class TestAskHappyPath(unittest.TestCase):
    def setUp(self) -> None:
        # Reset stats so assertions aren't polluted by other tests.
        gw._CALL_STATS["total_calls"] = 0
        gw._CALL_STATS["total_cost_usd"] = 0.0
        gw._CALL_STATS["total_latency_ms"] = 0.0
        gw._CALL_STATS["by_purpose"] = {}
        gw._CALL_STATS["by_adapter"] = {}
        gw._CALL_STATS["failures"] = 0

    def test_ok_path_routes_through_adapter(self) -> None:
        fake_result = MagicMock(
            ok=True,
            data={"text": "hello world"},
            tokens_in=10, tokens_out=20,
            adapter="groq", model="llama-3.3",
            error=None,
        )
        fake_router = MagicMock(
            execute=MagicMock(return_value=fake_result),
        )
        with patch("core.adapters.get_router", return_value=fake_router), \
             patch("core.adapters.Capability", MagicMock()), \
             patch("core.adapters.RouteContext", MagicMock()):
            r = gw.ask("say hi", purpose="reasoning")
        self.assertTrue(r.ok)
        self.assertEqual(r.text, "hello world")
        self.assertEqual(r.adapter, "groq")
        self.assertEqual(r.tokens_in, 10)
        self.assertEqual(r.tokens_out, 20)

    def test_stats_accumulate(self) -> None:
        fake_result = MagicMock(
            ok=True, data={"text": "x"},
            tokens_in=1, tokens_out=1,
            adapter="groq", model="x",
        )
        fake_router = MagicMock(
            execute=MagicMock(return_value=fake_result),
        )
        with patch("core.adapters.get_router", return_value=fake_router), \
             patch("core.adapters.Capability", MagicMock()), \
             patch("core.adapters.RouteContext", MagicMock()):
            gw.ask("a", purpose="bulk")
            gw.ask("b", purpose="bulk")
        s = gw.stats()
        self.assertGreaterEqual(s["total_calls"], 2)
        self.assertEqual(s["by_purpose"].get("bulk", 0), 2)

    def test_adapter_failure_recorded_as_failure(self) -> None:
        fake_result = MagicMock(
            ok=False, data=None,
            tokens_in=0, tokens_out=0,
            adapter="groq", model="",
            error="rate limit",
        )
        fake_router = MagicMock(
            execute=MagicMock(return_value=fake_result),
        )
        with patch("core.adapters.get_router", return_value=fake_router), \
             patch("core.adapters.Capability", MagicMock()), \
             patch("core.adapters.RouteContext", MagicMock()):
            r = gw.ask("x")
        self.assertFalse(r.ok)

    def test_router_raises_caught_gracefully(self) -> None:
        fake_router = MagicMock(
            execute=MagicMock(side_effect=RuntimeError("boom")),
        )
        with patch("core.adapters.get_router", return_value=fake_router), \
             patch("core.adapters.Capability", MagicMock()), \
             patch("core.adapters.RouteContext", MagicMock()):
            r = gw.ask("x")
        self.assertFalse(r.ok)
        self.assertIn("boom", r.error)


class TestBudgetTable(unittest.TestCase):
    def test_purpose_budgets_present(self) -> None:
        for purpose in ("bulk", "content", "reasoning", "cycle_block"):
            self.assertIn(purpose, gw._BUDGETS)

    def test_budgets_are_monotonic(self) -> None:
        self.assertLess(
            gw._BUDGETS["bulk"]["max_cost"],
            gw._BUDGETS["content"]["max_cost"],
        )
        self.assertLess(
            gw._BUDGETS["content"]["max_cost"],
            gw._BUDGETS["reasoning"]["max_cost"],
        )


class TestResultDict(unittest.TestCase):
    def test_result_serialises(self) -> None:
        r = gw.GatewayResult(
            ok=True, text="x", adapter="groq",
            tokens_in=1, tokens_out=2, cost_usd=0.001,
            latency_ms=123.4, purpose="bulk",
        )
        d = r.as_dict()
        self.assertEqual(d["adapter"], "groq")
        self.assertEqual(d["purpose"], "bulk")


if __name__ == "__main__":
    unittest.main()
