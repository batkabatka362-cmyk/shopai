"""LLM dispatcher tests."""
from __future__ import annotations

import unittest

from core.system import llm_dispatcher as ld


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.d = ld.LLMDispatcher()
        # Clear defaults to start from scratch
        for m in self.d.registered():
            self.d.deregister(m.name)

    def test_register_and_list(self) -> None:
        self.d.register(
            "m", {"classify"}, cost_per_1k_tokens=0.001,
        )
        names = [m.name for m in self.d.registered()]
        self.assertEqual(names, ["m"])

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.d.register(
                "", {"x"}, cost_per_1k_tokens=0.001,
            )

    def test_deregister(self) -> None:
        self.d.register("m", {"x"}, 0.001)
        self.assertTrue(self.d.deregister("m"))
        self.assertFalse(self.d.deregister("m"))


class TestDispatch(unittest.TestCase):
    def setUp(self) -> None:
        self.d = ld.LLMDispatcher()
        for m in self.d.registered():
            self.d.deregister(m.name)
        self.d.register(
            "cheap", {"classify"},
            cost_per_1k_tokens=0.0001, typical_latency_s=1.0,
        )
        self.d.register(
            "expensive", {"classify", "reason"},
            cost_per_1k_tokens=0.01, typical_latency_s=5.0,
        )
        self.d.register(
            "too_small", {"classify"},
            cost_per_1k_tokens=0.00005,
            typical_latency_s=0.5,
            max_tokens=100,
        )

    def test_cheapest_capable_wins(self) -> None:
        req = ld.Request(
            required_capabilities=frozenset({"classify"}),
            estimated_tokens=500,
        )
        res = self.d.dispatch(req)
        # 'too_small' rejected for context; cheap wins
        self.assertEqual(res.best.name, "cheap")

    def test_capability_required(self) -> None:
        req = ld.Request(
            required_capabilities=frozenset({"reason"}),
            estimated_tokens=500,
        )
        res = self.d.dispatch(req)
        self.assertEqual(res.best.name, "expensive")

    def test_latency_cap_filters(self) -> None:
        req = ld.Request(
            required_capabilities=frozenset({"classify"}),
            estimated_tokens=50,        # fits 'too_small' too
            max_latency_s=0.8,
        )
        res = self.d.dispatch(req)
        # Only the tiny-context one is fast enough
        self.assertEqual(res.best.name, "too_small")

    def test_excluded_dropped(self) -> None:
        req = ld.Request(
            required_capabilities=frozenset({"classify"}),
            exclude=frozenset({"cheap"}),
        )
        res = self.d.dispatch(req)
        # cheap is out → expensive wins
        names = [m.name for m in res.ordered_candidates]
        self.assertNotIn("cheap", names)

    def test_rejected_carries_reason(self) -> None:
        req = ld.Request(
            required_capabilities=frozenset({"reason"}),
        )
        res = self.d.dispatch(req)
        rejected_names = {n for n, _ in res.rejected}
        self.assertIn("cheap", rejected_names)


class TestInvoke(unittest.TestCase):
    def setUp(self) -> None:
        self.d = ld.LLMDispatcher()
        for m in self.d.registered():
            self.d.deregister(m.name)
        self.d.register(
            "a", {"classify"}, cost_per_1k_tokens=0.0001,
        )
        self.d.register(
            "b", {"classify"}, cost_per_1k_tokens=0.001,
        )

    def test_invoke_uses_cheapest(self) -> None:
        called = []
        def run(m):
            called.append(m.name)
            return "ok"
        req = ld.Request(
            required_capabilities=frozenset({"classify"}),
        )
        used, result, errors = self.d.invoke(req, run)
        self.assertEqual(used.name, "a")
        self.assertEqual(result, "ok")
        self.assertEqual(errors, [])

    def test_invoke_falls_back(self) -> None:
        def run(m):
            if m.name == "a":
                raise RuntimeError("a down")
            return "fallback"
        req = ld.Request(
            required_capabilities=frozenset({"classify"}),
        )
        used, result, errors = self.d.invoke(req, run)
        self.assertEqual(used.name, "b")
        self.assertEqual(result, "fallback")
        self.assertEqual(len(errors), 1)

    def test_invoke_all_fail_returns_none(self) -> None:
        def run(m):
            raise RuntimeError("all down")
        req = ld.Request(
            required_capabilities=frozenset({"classify"}),
        )
        used, result, errors = self.d.invoke(req, run)
        self.assertIsNone(used)
        self.assertIsNone(result)
        self.assertEqual(len(errors), 2)


class TestDefaults(unittest.TestCase):
    def test_defaults_registered(self) -> None:
        d = ld.LLMDispatcher()
        names = [m.name for m in d.registered()]
        self.assertIn("groq_llama3_70b", names)
        self.assertIn("gemini_flash", names)
        self.assertIn("deepseek_v3", names)


class TestSingleton(unittest.TestCase):
    def test_singleton_returns_same_instance(self) -> None:
        self.assertIs(ld.dispatcher(), ld.dispatcher())


if __name__ == "__main__":
    unittest.main()
