"""BrainFacade module-registrar tests (quality audit item #9).

Adds a ``register_module / module / unregister_module /
registered_modules`` API so future brain subsystems can
self-register via a zero-arg factory instead of editing the
5400-line facade. Lazy + cached + failure-isolated.
"""
from __future__ import annotations

import unittest

from core.brain.brain_facade import BrainFacade


class TestRegister(unittest.TestCase):
    def test_register_then_module_returns_instance(self):
        facade = BrainFacade()
        sentinel = object()
        facade.register_module(
            "demo", lambda: sentinel,
        )
        self.assertIs(facade.module("demo"), sentinel)

    def test_missing_name_raises(self):
        facade = BrainFacade()
        with self.assertRaises(ValueError):
            facade.register_module("", lambda: 1)

    def test_non_callable_factory_raises(self):
        facade = BrainFacade()
        with self.assertRaises(ValueError):
            facade.register_module("demo", 42)

    def test_module_unknown_returns_none(self):
        facade = BrainFacade()
        self.assertIsNone(facade.module("absent"))

    def test_module_caches(self):
        facade = BrainFacade()
        calls = {"n": 0}

        def _factory():
            calls["n"] += 1
            return object()

        facade.register_module("demo", _factory)
        first = facade.module("demo")
        second = facade.module("demo")
        self.assertIs(first, second)
        self.assertEqual(calls["n"], 1)

    def test_factory_failure_returns_none(self):
        facade = BrainFacade()

        def _factory():
            raise RuntimeError("boom")

        facade.register_module("demo", _factory)
        self.assertIsNone(facade.module("demo"))
        # Cache empty so a later re-register works
        facade.register_module(
            "demo", lambda: "ok",
        )
        self.assertEqual(facade.module("demo"), "ok")

    def test_reregister_replaces_factory(self):
        facade = BrainFacade()
        facade.register_module("demo", lambda: "v1")
        self.assertEqual(facade.module("demo"), "v1")
        facade.register_module("demo", lambda: "v2")
        self.assertEqual(facade.module("demo"), "v2")

    def test_unregister_removes(self):
        facade = BrainFacade()
        facade.register_module("demo", lambda: 1)
        self.assertTrue(
            facade.unregister_module("demo"),
        )
        self.assertIsNone(facade.module("demo"))

    def test_unregister_absent_false(self):
        facade = BrainFacade()
        self.assertFalse(
            facade.unregister_module("absent"),
        )

    def test_registered_modules_lists_names(self):
        facade = BrainFacade()
        facade.register_module("b", lambda: 1)
        facade.register_module("a", lambda: 2)
        self.assertEqual(
            facade.registered_modules(), ("a", "b"),
        )


class TestIsolation(unittest.TestCase):
    """Registration on one facade instance doesn't leak into
    a fresh one (important for test isolation + future
    multi-tenancy)."""

    def test_separate_instances(self):
        a = BrainFacade()
        b = BrainFacade()
        a.register_module("only_a", lambda: 1)
        self.assertEqual(a.module("only_a"), 1)
        self.assertIsNone(b.module("only_a"))


class TestSingletonWorks(unittest.TestCase):
    """The canonical singleton returned by ``brain()`` must
    also accept registrations — owner workflow is register
    once at import time, read later."""

    def test_singleton_accepts_registration(self):
        from core.brain.brain_facade import brain
        b = brain()
        b.register_module(
            "_audit_smoke", lambda: {"wired": True},
        )
        try:
            self.assertEqual(
                b.module("_audit_smoke"),
                {"wired": True},
            )
            self.assertIn(
                "_audit_smoke", b.registered_modules(),
            )
        finally:
            b.unregister_module("_audit_smoke")


if __name__ == "__main__":
    unittest.main()
