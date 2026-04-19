"""Invariant monitor tests."""
from __future__ import annotations

import unittest

from core.brain import invariant_monitor as im


class TestInvariant(unittest.TestCase):
    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            im.Invariant(name="", predicate=lambda s: True)

    def test_bad_severity_raises(self) -> None:
        with self.assertRaises(ValueError):
            im.Invariant(
                name="x", predicate=lambda s: True,
                severity="fatal",  # type: ignore
            )

    def test_holds_catches_predicate_exception(self) -> None:
        def boom(_):
            raise RuntimeError("x")

        inv = im.Invariant(name="x", predicate=boom)
        self.assertFalse(inv.holds({}))   # fail closed


class TestRegister(unittest.TestCase):
    def test_duplicate_rejected(self) -> None:
        m = im.InvariantMonitor()
        inv = im.Invariant(name="x", predicate=lambda s: True)
        m.register(inv)
        with self.assertRaises(ValueError):
            m.register(inv)

    def test_overwrite_allowed(self) -> None:
        m = im.InvariantMonitor()
        m.register(im.Invariant(name="x", predicate=lambda s: True))
        m.register(
            im.Invariant(name="x", predicate=lambda s: False),
            overwrite=True,
        )
        report = m.check({})
        self.assertEqual(len(report.breaches), 1)

    def test_unregister(self) -> None:
        m = im.InvariantMonitor()
        m.register(im.Invariant(name="x", predicate=lambda s: True))
        self.assertTrue(m.unregister("x"))
        self.assertFalse(m.unregister("x"))

    def test_bad_alert_after_raises(self) -> None:
        with self.assertRaises(ValueError):
            im.InvariantMonitor(alert_after=0)


class TestCheck(unittest.TestCase):
    def test_all_hold_no_breaches(self) -> None:
        m = im.InvariantMonitor()
        m.register(im.Invariant(name="x", predicate=lambda s: True))
        report = m.check({})
        self.assertEqual(report.breaches, [])
        self.assertEqual(report.alerts, [])

    def test_breach_captured(self) -> None:
        m = im.InvariantMonitor()
        m.register(im.Invariant(
            name="x", predicate=lambda s: False,
            severity="warning", message="always broken",
        ))
        report = m.check({})
        self.assertEqual(len(report.breaches), 1)
        self.assertEqual(report.breaches[0].invariant, "x")

    def test_streak_increments(self) -> None:
        m = im.InvariantMonitor()
        m.register(im.Invariant(name="x", predicate=lambda s: False))
        m.check({})
        m.check({})
        m.check({})
        self.assertEqual(m.streak("x"), 3)
        self.assertEqual(m.total("x"), 3)

    def test_streak_resets_when_invariant_holds(self) -> None:
        flip = {"n": 0}

        def pred(_):
            flip["n"] += 1
            return flip["n"] > 2  # fails first 2 checks, passes thereafter

        m = im.InvariantMonitor()
        m.register(im.Invariant(name="x", predicate=pred))
        m.check({}); m.check({})
        self.assertEqual(m.streak("x"), 2)
        m.check({})
        self.assertEqual(m.streak("x"), 0)

    def test_alert_fires_after_threshold(self) -> None:
        m = im.InvariantMonitor(alert_after=3)
        m.register(im.Invariant(name="x", predicate=lambda s: False))
        for _ in range(2):
            r = m.check({})
            self.assertEqual(r.alerts, [])
        r = m.check({})
        self.assertEqual(len(r.alerts), 1)


class TestResolve(unittest.TestCase):
    def test_resolve_clears_streak(self) -> None:
        m = im.InvariantMonitor()
        m.register(im.Invariant(name="x", predicate=lambda s: False))
        m.check({}); m.check({})
        self.assertTrue(m.resolve("x"))
        self.assertEqual(m.streak("x"), 0)

    def test_resolve_unknown_false(self) -> None:
        m = im.InvariantMonitor()
        self.assertFalse(m.resolve("nobody"))


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        m = im.InvariantMonitor()
        m.register(im.Invariant(name="x", predicate=lambda s: False))
        m.register(im.Invariant(name="y", predicate=lambda s: True))
        m.check({})
        s = m.stats()
        self.assertEqual(s["invariants"], 2)
        self.assertGreaterEqual(s["active_breaches"], 1)
        self.assertIn("x", s["by_name"])


class TestCanonical(unittest.TestCase):
    def test_inventory_non_negative(self) -> None:
        inv = im.inventory_non_negative()
        ok = inv.holds({
            "products": [{"on_hand": 5}, {"on_hand": 0}],
        })
        self.assertTrue(ok)
        bad = inv.holds({
            "products": [{"on_hand": 5}, {"on_hand": -1}],
        })
        self.assertFalse(bad)

    def test_refunds_le_orders(self) -> None:
        inv = im.refunds_le_orders()
        ok = inv.holds({
            "orders": [{"amount": 100}],
            "refunds": [{"amount": 20}],
        })
        self.assertTrue(ok)
        bad = inv.holds({
            "orders": [{"amount": 100}],
            "refunds": [{"amount": 150}],
        })
        self.assertFalse(bad)

    def test_positive_margin(self) -> None:
        inv = im.positive_margin()
        ok = inv.holds({
            "products": [{"margin": 0.3}, {"margin": 0.1}],
        })
        self.assertTrue(ok)
        bad = inv.holds({
            "products": [{"margin": 0.3}, {"margin": -0.05}],
        })
        self.assertFalse(bad)

    def test_positive_margin_ignores_missing(self) -> None:
        inv = im.positive_margin()
        # No margin field → skipped, still holds
        self.assertTrue(inv.holds({"products": [{"name": "x"}]}))


class TestDict(unittest.TestCase):
    def test_report_serialises(self) -> None:
        m = im.InvariantMonitor()
        m.register(im.Invariant(name="x", predicate=lambda s: False))
        d = m.check({}).as_dict()
        self.assertIn("breaches", d)


if __name__ == "__main__":
    unittest.main()
