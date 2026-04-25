"""C3 consolidation — ``core.memory`` re-exports the 4 legacy
storage primitives so new code can use a single canonical
path. This test locks in:

  1. Both import paths resolve to the same class object
     (no silent divergence).
  2. The primitives still work through the new path.
  3. Migrated call sites import from core.memory.
"""
from __future__ import annotations

import pathlib
import unittest


class TestClassIdentity(unittest.TestCase):
    def test_short_term_cache_identity(self):
        from core.memory import ShortTermCache as new_cls
        from memory import ShortTermCache as old_cls
        self.assertIs(new_cls, old_cls)

    def test_persistent_store_identity(self):
        from core.memory import PersistentStore as new_cls
        from memory import PersistentStore as old_cls
        self.assertIs(new_cls, old_cls)

    def test_vector_db_identity(self):
        from core.memory import VectorDB as new_cls
        from memory import VectorDB as old_cls
        self.assertIs(new_cls, old_cls)

    def test_embedding_manager_identity(self):
        from core.memory import EmbeddingManager as new_cls
        from memory import EmbeddingManager as old_cls
        self.assertIs(new_cls, old_cls)


class TestWorking(unittest.TestCase):
    def test_cache_round_trip_via_new_path(self):
        from core.memory import ShortTermCache
        c = ShortTermCache(max_size=10)
        c.set("k", 42, ttl=30)
        self.assertEqual(c.get("k"), 42)
        self.assertTrue(c.delete("k"))
        self.assertIsNone(c.get("k"))


class TestMigratedCallSites(unittest.TestCase):
    """Grep-based assertion: migrated files import from
    core.memory. Reversing any of these is caught here."""

    REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

    def _read(self, rel: str) -> str:
        return (self.REPO_ROOT / rel).read_text()

    def test_auto_recovery_uses_core_memory(self):
        src = self._read(
            "core/self_monitor/auto_recovery.py",
        )
        self.assertIn(
            "from core.memory import ShortTermCache", src,
        )

    def test_health_checker_uses_core_memory(self):
        src = self._read(
            "core/self_monitor/health_checker.py",
        )
        self.assertIn(
            "from core.memory import ShortTermCache",
            src,
        )

    def test_full_system_loop_uses_core_memory(self):
        src = self._read("core/full_system_loop.py")
        self.assertIn(
            "from core.memory import VectorDB", src,
        )
        self.assertIn(
            "from core.memory import ShortTermCache", src,
        )

    def test_main_orchestrator_uses_core_memory(self):
        src = self._read(
            "core/orchestrator/main_orchestrator.py",
        )
        self.assertIn(
            "from core.memory import VectorDB", src,
        )

    def test_controller_uses_core_memory(self):
        src = self._read(
            "core/autonomous/controller.py",
        )
        self.assertIn(
            "from core.memory import PersistentStore", src,
        )


if __name__ == "__main__":
    unittest.main()
