"""Regression tests for Fix I: multi_store_brain routing +
memory_sync deletion.

Core audit items #7 + #8 flagged three files as "dead code
or stubs":

  * ``core/brain/multi_store_brain.py`` — LIVE, not dead.
    Four production call sites (``core/autonomous/
    controller.py``, ``execution/store_cloner.py``,
    ``core/system/store_registry.py``, ``core/system/
    multi_store_manager.py``) register stores and sweep
    cross-store learning. What WAS broken was its direct
    import of ``core.memory.intelligence`` bypassing
    ``UnifiedMemory`` — the same Fix D consistency
    violation. Fix I routes it through UnifiedMemory.

  * ``core/memory/memory_router.py`` — LIVE, not a stub.
    One call site in ``MainOrchestrator.execute_task`` uses
    ``route_store`` to park task results in short-term
    memory. Keep as-is.

  * ``core/memory/memory_sync.py`` — DEAD. Instantiated in
    ``MainOrchestrator.__init__`` but none of
    ``promote/demote/add_promotion_rule/sync_stats`` is
    called anywhere in production or tests. Fix I deletes
    the file and the instantiation.

These tests pin the decisions so the files don't quietly
come back as zombies.
"""
from __future__ import annotations

import pathlib

import pytest


class TestMultiStoreBrainRoutesThroughUnifiedMemory:
    """``multi_store_brain.py`` must pull
    ``MemoryIntelligence`` via ``UnifiedMemory``, not via the
    legacy ``core.memory.intelligence`` direct import — same
    consolidation pattern as Fix D."""

    def test_source_has_no_direct_memory_intelligence_import(self):
        import re
        text = pathlib.Path("core/brain/multi_store_brain.py").read_text(
            encoding="utf-8",
        )
        assert not re.search(
            r"from\s+core\.memory\.intelligence\s+import\s+get_memory_intelligence",
            text,
        ), (
            "multi_store_brain.py still imports get_memory_intelligence "
            "directly from core.memory.intelligence — Fix I routes "
            "this through UnifiedMemory"
        )

    def test_source_uses_unified_memory(self):
        text = pathlib.Path("core/brain/multi_store_brain.py").read_text(
            encoding="utf-8",
        )
        assert "unified_memory" in text, (
            "multi_store_brain.py must import from "
            "core.memory.unified_memory after Fix I"
        )

    def test_share_learning_still_runs(self):
        """Contract test: the method still returns a dict with
        the expected keys after the rewiring."""
        from core.brain.multi_store_brain import get_multi_store
        ms = get_multi_store()
        ms.register_store("fix_i_test_store")
        shared = ms.share_learning("fix_i_test_store")
        assert isinstance(shared, dict)
        # Either it routed successfully (has shareable_rules) or
        # UnifiedMemory returned unavailable — both are valid
        # runtime outcomes depending on whether memory is
        # initialized in this process.
        assert (
            "shareable_rules" in shared or shared.get("status") == "unavailable"
        )

    def test_apply_learning_still_runs(self):
        from core.brain.multi_store_brain import get_multi_store
        ms = get_multi_store()
        ms.register_store("fix_i_target")
        result = ms.apply_learning("fix_i_target", {"rules": []})
        assert isinstance(result, dict)
        assert "applied_rules" in result or result.get("status") == "unavailable"

    def test_share_learning_routes_through_unified_memory(self, monkeypatch):
        """Track that ``share_learning`` calls
        ``get_unified_memory()`` at least once — proves the
        runtime path uses the unified entry point, not the
        bypassed import."""
        import core.memory.unified_memory as um_mod

        hits = {"count": 0}
        original = um_mod.get_unified_memory

        def _tracking():
            hits["count"] += 1
            return original()

        monkeypatch.setattr(um_mod, "get_unified_memory", _tracking)

        from core.brain.multi_store_brain import get_multi_store
        ms = get_multi_store()
        ms.register_store("fix_i_router_track")
        ms.share_learning("fix_i_router_track")

        assert hits["count"] >= 1, (
            "share_learning did not route through "
            "UnifiedMemory — Fix I requires the unified entry point"
        )


class TestMemorySyncDeleted:
    """The dead ``MemorySync`` class must be removed: file
    gone, ``__init__`` export gone, MainOrchestrator
    instantiation gone."""

    def test_memory_sync_file_deleted(self):
        assert not pathlib.Path("core/memory/memory_sync.py").exists(), (
            "core/memory/memory_sync.py still exists — Fix I "
            "deleted it because no caller touched "
            "promote/demote/sync_stats"
        )

    def test_memory_sync_not_in_memory_init(self):
        text = pathlib.Path("core/memory/__init__.py").read_text(
            encoding="utf-8",
        )
        assert "MemorySync" not in text
        assert "memory_sync" not in text

    def test_memory_sync_not_in_main_orchestrator(self):
        import re
        text = pathlib.Path("core/orchestrator/main_orchestrator.py").read_text(
            encoding="utf-8",
        )
        # No import of MemorySync (allow the word inside
        # comments explaining why it was removed)
        assert not re.search(
            r"from\s+core\.memory\.memory_sync\s+import", text,
        ), "MainOrchestrator still imports MemorySync"
        assert not re.search(r"^\s*self\._memory_sync\s*=", text, re.MULTILINE), (
            "MainOrchestrator still assigns self._memory_sync"
        )
        # Also make sure MemorySync() is not being called
        assert "MemorySync(" not in text, (
            "MainOrchestrator still instantiates MemorySync"
        )

    def test_cannot_import_memory_sync(self):
        with pytest.raises(ImportError):
            from core.memory.memory_sync import MemorySync  # noqa: F401


class TestMemoryRouterStillWorks:
    """``memory_router`` is NOT a stub — it has one active
    caller in MainOrchestrator. Keep it alive."""

    def test_memory_router_file_still_exists(self):
        assert pathlib.Path("core/memory/memory_router.py").exists()

    def test_memory_router_still_importable(self):
        from core.memory.memory_router import MemoryRouter
        from core.memory.memory_manager import MemoryManager
        r = MemoryRouter(MemoryManager())
        assert r is not None

    def test_main_orchestrator_still_uses_router(self):
        text = pathlib.Path("core/orchestrator/main_orchestrator.py").read_text(
            encoding="utf-8",
        )
        assert "MemoryRouter" in text
        assert "_memory_router" in text

    def test_memory_router_route_store_contract(self, tmp_path):
        from core.memory.memory_router import MemoryRouter
        from core.memory.memory_manager import MemoryManager
        r = MemoryRouter(MemoryManager())
        dest = r.route_store("k1", {"x": 1}, data_type="task_result")
        assert dest == "short_term"


class TestMainOrchestratorCleanInit:
    """MainOrchestrator's ``__init__`` must still build a
    working instance with the MemorySync line removed."""

    def test_main_orchestrator_still_constructs(self):
        from core.orchestrator.main_orchestrator import MainOrchestrator
        orch = MainOrchestrator()
        assert orch is not None
        # The router is still there
        assert hasattr(orch, "_memory_router")
        # The sync attribute is gone
        assert not hasattr(orch, "_memory_sync")
