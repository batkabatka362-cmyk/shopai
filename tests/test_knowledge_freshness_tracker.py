"""Knowledge freshness tracker tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.memory import knowledge_freshness_tracker as kft


class TestConfig(unittest.TestCase):
    def test_bad_half_life_raises(self) -> None:
        with self.assertRaises(ValueError):
            kft.KnowledgeFreshnessTracker(
                default_half_life_s=0,
            )


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        self.t = kft.KnowledgeFreshnessTracker()

    def test_blank_key_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.register(key="")

    def test_blank_kind_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.register(key="k", kind="")

    def test_bad_half_life_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.register(
                key="k", half_life_seconds=0,
            )

    def test_register_creates(self) -> None:
        item = self.t.register(
            key="niche.pet.aov", kind="stat", ts=100.0,
        )
        self.assertEqual(item.evidence_count, 1)

    def test_register_idempotent(self) -> None:
        self.t.register(key="k", ts=100.0)
        self.t.register(key="k", ts=200.0)
        # Only one item
        self.assertEqual(self.t.stats()["total"], 1)


class TestFreshness(unittest.TestCase):
    def test_fresh_at_birth(self) -> None:
        t = kft.KnowledgeFreshnessTracker()
        t.register(key="k", ts=100.0)
        self.assertAlmostEqual(
            t.freshness("k", now=100.0), 1.0, places=4,
        )

    def test_half_life_decays_to_half(self) -> None:
        t = kft.KnowledgeFreshnessTracker(
            default_half_life_s=100.0,
        )
        t.register(key="k", ts=0.0)
        self.assertAlmostEqual(
            t.freshness("k", now=100.0), 0.5, places=4,
        )

    def test_unknown_returns_zero(self) -> None:
        t = kft.KnowledgeFreshnessTracker()
        self.assertEqual(t.freshness("nope"), 0.0)


class TestRefresh(unittest.TestCase):
    def setUp(self) -> None:
        self.t = kft.KnowledgeFreshnessTracker(
            default_half_life_s=100.0,
        )
        self.t.register(key="k", ts=0.0)

    def test_refresh_resets_freshness(self) -> None:
        self.t.refresh("k", ts=50.0)
        # Decayed to 0.5 at t=150, but we refreshed at 50
        self.assertAlmostEqual(
            self.t.freshness("k", now=50.0), 1.0, places=4,
        )

    def test_refresh_increments_evidence(self) -> None:
        self.t.refresh("k", confirm=True)
        item = self.t.get("k")
        self.assertEqual(item.evidence_count, 2)
        self.assertEqual(item.confirm_count, 1)

    def test_refresh_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.t.refresh("nope")


class TestContradict(unittest.TestCase):
    def setUp(self) -> None:
        self.t = kft.KnowledgeFreshnessTracker(
            default_half_life_s=100.0,
        )
        self.t.register(key="k", ts=0.0)

    def test_contradict_increments(self) -> None:
        self.t.contradict("k")
        item = self.t.get("k")
        self.assertEqual(item.contradict_count, 1)

    def test_contradict_shrinks_half_life(self) -> None:
        before = self.t.get("k").half_life_seconds
        self.t.contradict("k")
        after = self.t.get("k").half_life_seconds
        self.assertLess(after, before)


class TestStale(unittest.TestCase):
    def test_stale_filter(self) -> None:
        t = kft.KnowledgeFreshnessTracker(
            default_half_life_s=100.0,
        )
        t.register(key="old", ts=0.0)
        t.register(key="new", ts=1000.0)
        stale = t.stale(cutoff=0.5, now=1000.0)
        keys = [s.key for s in stale]
        self.assertIn("old", keys)
        self.assertNotIn("new", keys)

    def test_bad_cutoff_raises(self) -> None:
        t = kft.KnowledgeFreshnessTracker()
        with self.assertRaises(ValueError):
            t.stale(cutoff=0.0)


class TestByKind(unittest.TestCase):
    def test_filter_by_kind(self) -> None:
        t = kft.KnowledgeFreshnessTracker()
        t.register(key="r1", kind="rule")
        t.register(key="r2", kind="rule")
        t.register(key="s1", kind="stat")
        self.assertEqual(len(t.by_kind("rule")), 2)
        self.assertEqual(len(t.by_kind("stat")), 1)


class TestPersistence(unittest.TestCase):
    def test_survives_reopen(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "k.db"
        first = kft.KnowledgeFreshnessTracker(path)
        first.register(
            key="k", kind="rule", half_life_seconds=500,
        )
        first.refresh("k")
        first.close()
        second = kft.KnowledgeFreshnessTracker(path)
        item = second.get("k")
        self.assertEqual(item.evidence_count, 2)
        self.assertEqual(item.half_life_seconds, 500)
        second.close()
        tmp.cleanup()


class TestStats(unittest.TestCase):
    def test_stats_shape(self) -> None:
        t = kft.KnowledgeFreshnessTracker()
        t.register(key="k", kind="rule")
        s = t.stats()
        self.assertEqual(s["total"], 1)
        self.assertEqual(s["by_kind"]["rule"], 1)


class TestReset(unittest.TestCase):
    def test_reset(self) -> None:
        t = kft.KnowledgeFreshnessTracker()
        t.register(key="k")
        self.assertEqual(t.reset(), 1)


class TestDict(unittest.TestCase):
    def test_serialises(self) -> None:
        t = kft.KnowledgeFreshnessTracker()
        item = t.register(key="k", kind="rule")
        d = item.as_dict()
        self.assertIn("freshness", d)
        self.assertEqual(d["key"], "k")


if __name__ == "__main__":
    unittest.main()
