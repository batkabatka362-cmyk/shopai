"""Feature flags tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.system import feature_flags as ff


class TestBool(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.f = ff.FeatureFlags(Path(self._tmp.name) / "f.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_bool_on(self) -> None:
        self.f.set_bool("dark_mode", True)
        self.assertTrue(self.f.is_enabled("dark_mode"))

    def test_bool_off(self) -> None:
        self.f.set_bool("dark_mode", False)
        self.assertFalse(self.f.is_enabled("dark_mode"))

    def test_unknown_is_off(self) -> None:
        self.assertFalse(self.f.is_enabled("never_set"))


class TestPercentage(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.f = ff.FeatureFlags(Path(self._tmp.name) / "f.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_full_enables_everyone(self) -> None:
        self.f.set_percentage("new_checkout", 100)
        self.assertTrue(
            self.f.is_enabled("new_checkout", entity_id="x"),
        )

    def test_zero_disables_everyone(self) -> None:
        self.f.set_percentage("new_checkout", 0)
        self.assertFalse(
            self.f.is_enabled("new_checkout", entity_id="x"),
        )

    def test_half_splits_roughly(self) -> None:
        self.f.set_percentage("ab", 50)
        enabled = sum(
            1 for i in range(200)
            if self.f.is_enabled("ab", entity_id=f"e{i}")
        )
        # Expect ~50/200 on ±15 tolerance
        self.assertGreater(enabled, 70)
        self.assertLess(enabled, 130)

    def test_sticky_per_entity(self) -> None:
        self.f.set_percentage("ab", 50)
        first = self.f.is_enabled("ab", entity_id="same")
        for _ in range(10):
            self.assertEqual(
                self.f.is_enabled("ab", entity_id="same"), first,
            )

    def test_clamped(self) -> None:
        self.f.set_percentage("x", 500)
        self.assertEqual(self.f.pct("x"), 100.0)


class TestAttribute(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.f = ff.FeatureFlags(Path(self._tmp.name) / "f.json")
        self.f.set_attribute(
            "premium_feature", {"tier": "pro"},
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_matches_attribute(self) -> None:
        self.assertTrue(
            self.f.is_enabled("premium_feature", attrs={"tier": "pro"}),
        )

    def test_missing_attribute_disables(self) -> None:
        self.assertFalse(
            self.f.is_enabled(
                "premium_feature", attrs={"tier": "free"},
            ),
        )
        self.assertFalse(self.f.is_enabled("premium_feature"))


class TestVariant(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.f = ff.FeatureFlags(Path(self._tmp.name) / "f.json")
        self.f.set_variant("ab", {"A": 50, "B": 50})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_returns_one_of_variants(self) -> None:
        v = self.f.variant("ab", entity_id="u1")
        self.assertIn(v, ("A", "B"))

    def test_sticky_variant(self) -> None:
        first = self.f.variant("ab", entity_id="u1")
        for _ in range(20):
            self.assertEqual(
                self.f.variant("ab", entity_id="u1"), first,
            )

    def test_unknown_flag_returns_none(self) -> None:
        self.assertIsNone(self.f.variant("missing"))

    def test_empty_weights_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.f.set_variant("bad", {})

    def test_unnormalised_weights_accepted(self) -> None:
        # Non-normalised weights should still work
        self.f.set_variant("ab2", {"A": 3, "B": 7})
        v = self.f.variant("ab2", entity_id="u1")
        self.assertIn(v, ("A", "B"))


class TestPersistence(unittest.TestCase):
    def test_flags_persist_across_reload(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "f.json"
        f1 = ff.FeatureFlags(path)
        f1.set_bool("persisted", True)
        f2 = ff.FeatureFlags(path)
        self.assertTrue(f2.is_enabled("persisted"))
        tmp.cleanup()


class TestDelete(unittest.TestCase):
    def test_delete_removes(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        f = ff.FeatureFlags(Path(tmp.name) / "f.json")
        f.set_bool("x", True)
        self.assertTrue(f.delete("x"))
        self.assertFalse(f.is_enabled("x"))
        tmp.cleanup()

    def test_delete_unknown_false(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        f = ff.FeatureFlags(Path(tmp.name) / "f.json")
        self.assertFalse(f.delete("nope"))
        tmp.cleanup()


class TestSingleton(unittest.TestCase):
    def test_flags_returns_same(self) -> None:
        self.assertIs(ff.flags(), ff.flags())


if __name__ == "__main__":
    unittest.main()
