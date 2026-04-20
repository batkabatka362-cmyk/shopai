"""Tests for core.federation singleton accessor."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from core.federation import (
    MultiStoreFederator,
    get_federator,
    reset_federator_for_tests,
)


class TestSingleton(unittest.TestCase):
    def setUp(self):
        reset_federator_for_tests()
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        reset_federator_for_tests()
        self._tmp.cleanup()

    def test_get_returns_same_instance(self):
        a = get_federator(
            db_path=Path(self._tmp.name) / "f.db",
        )
        b = get_federator()
        self.assertIs(a, b)

    def test_returns_federator_type(self):
        fed = get_federator(
            db_path=Path(self._tmp.name) / "f.db",
        )
        self.assertIsInstance(fed, MultiStoreFederator)

    def test_persists_across_reset(self):
        path = Path(self._tmp.name) / "f.db"
        fed = get_federator(db_path=path)
        fed.register_store(
            "store_a", traits={"niche": "pet"},
        )
        fed.observe(
            "store_a", "kill_at_roas_1.5",
            wins=8, uses=10,
        )
        reset_federator_for_tests()
        fed2 = get_federator(db_path=path)
        self.assertEqual(len(fed2.stores()), 1)
        self.assertEqual(
            fed2.stores()[0].store_id, "store_a",
        )

    def test_reset_clears_singleton(self):
        a = get_federator(
            db_path=Path(self._tmp.name) / "f.db",
        )
        reset_federator_for_tests()
        # Rebuild needed — use a fresh temp dir so the old file
        # closure doesn't accidentally wedge
        b = get_federator(
            db_path=Path(self._tmp.name) / "f2.db",
        )
        self.assertIsNot(a, b)


class TestCreatesDirectories(unittest.TestCase):
    def setUp(self):
        reset_federator_for_tests()

    def tearDown(self):
        reset_federator_for_tests()

    def test_parent_dir_auto_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "a" / "b" / "c" / "fed.db"
            fed = get_federator(db_path=nested)
            self.assertTrue(nested.parent.is_dir())
            fed.register_store("x")
            self.assertEqual(len(fed.stores()), 1)


if __name__ == "__main__":
    unittest.main()
