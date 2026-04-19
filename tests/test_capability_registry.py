"""Capability registry tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.brain import capability_registry as cr


class TestConfig(unittest.TestCase):
    def test_bad_floor_raises(self) -> None:
        with self.assertRaises(ValueError):
            cr.CapabilityRegistry(proficiency_floor=0)
        with self.assertRaises(ValueError):
            cr.CapabilityRegistry(proficiency_floor=1.5)


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.r = cr.CapabilityRegistry()

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.register(name="", scope="s")

    def test_blank_scope_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.register(name="n", scope="")

    def test_bad_proficiency_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.register(
                name="n", scope="s",
                initial_proficiency=2.0,
            )

    def test_register_creates(self) -> None:
        c = self.r.register(
            name="update_price",
            scope="shopify.products",
            initial_proficiency=0.8,
        )
        self.assertEqual(c.name, "update_price")
        self.assertEqual(c.proficiency, 0.8)

    def test_idempotent(self) -> None:
        self.r.register(name="x", scope="s")
        c = self.r.register(
            name="x", scope="other",
            initial_proficiency=0.0,
        )
        self.assertEqual(c.scope, "s")


class TestGap(unittest.TestCase):
    def test_declare_gap(self) -> None:
        r = cr.CapabilityRegistry()
        c = r.declare_gap(
            name="generate_video",
            scope="creative.video",
            reason="no Replicate API adapter yet",
        )
        self.assertEqual(c.proficiency, 0.0)
        self.assertTrue(c.gap_reason)

    def test_blank_reason_raises(self) -> None:
        r = cr.CapabilityRegistry()
        with self.assertRaises(ValueError):
            r.declare_gap(
                name="x", scope="s", reason="",
            )


class TestUpdate(unittest.TestCase):
    def setUp(self) -> None:
        self.r = cr.CapabilityRegistry(proficiency_floor=0.6)
        self.r.register(
            name="x", scope="s",
            initial_proficiency=0.5,
        )

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.r.update("nope", ok=True)

    def test_first_update_overrides(self) -> None:
        c = self.r.update("x", ok=True)
        self.assertEqual(c.proficiency, 1.0)

    def test_ema_subsequent(self) -> None:
        self.r.update("x", ok=True)
        c = self.r.update("x", ok=False)
        self.assertAlmostEqual(c.proficiency, 0.9, places=4)

    def test_clearing_gap_on_improvement(self) -> None:
        self.r.declare_gap(
            name="y", scope="s", reason="no sample",
        )
        for _ in range(30):
            self.r.update("y", ok=True)
        c = self.r.capability("y")
        self.assertFalse(c.gap_reason)
        self.assertTrue(self.r.can_do("y"))


class TestQueries(unittest.TestCase):
    def setUp(self) -> None:
        self.r = cr.CapabilityRegistry(proficiency_floor=0.6)
        self.r.register(
            name="good", scope="a",
            initial_proficiency=0.8,
        )
        self.r.register(
            name="weak", scope="b",
            initial_proficiency=0.2,
        )
        self.r.declare_gap(
            name="missing", scope="c", reason="no adapter",
        )

    def test_can_do(self) -> None:
        self.assertTrue(self.r.can_do("good"))
        self.assertFalse(self.r.can_do("weak"))
        self.assertFalse(self.r.can_do("missing"))
        self.assertFalse(self.r.can_do("nope"))

    def test_gaps(self) -> None:
        g = [c.name for c in self.r.gaps()]
        self.assertIn("weak", g)
        self.assertIn("missing", g)

    def test_known_edges(self) -> None:
        e = self.r.known_edges()
        self.assertIn("b", e)
        self.assertIn("c", e)
        self.assertNotIn("a", e)

    def test_by_scope(self) -> None:
        c = self.r.by_scope("a")
        self.assertEqual(len(c), 1)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "c.db"
        first = cr.CapabilityRegistry(path)
        first.register(
            name="x", scope="s",
            initial_proficiency=0.7,
        )
        first.update("x", ok=True)
        first.close()
        second = cr.CapabilityRegistry(path)
        c = second.capability("x")
        self.assertEqual(c.sample_count, 1)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        r = cr.CapabilityRegistry(proficiency_floor=0.6)
        r.register(
            name="good", scope="s",
            initial_proficiency=0.8,
        )
        r.register(
            name="weak", scope="s",
            initial_proficiency=0.2,
        )
        s = r.stats()
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["ready"], 1)
        self.assertEqual(s["gaps"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        r = cr.CapabilityRegistry()
        r.register(name="x", scope="s")
        self.assertEqual(r.reset(), 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        r = cr.CapabilityRegistry()
        c = r.register(name="x", scope="s")
        d = c.as_dict()
        self.assertIn("proficiency", d)


if __name__ == "__main__":
    unittest.main()
