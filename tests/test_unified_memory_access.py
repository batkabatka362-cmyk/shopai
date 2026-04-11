"""Regression tests for Fix D: unified memory access.

Pre-fix ``DecisionBrain`` and ``DecisionEngine`` imported
``core.brain.memory.get_brain_memory`` and
``core.memory.intelligence.get_memory_intelligence``
DIRECTLY, bypassing ``UnifiedMemory`` entirely. This left
two parallel SQLite databases (``brain_memory.db`` +
``memory_intelligence.db``) with no single owner, and every
future observability / backend-swap effort would require a
grep of every brain file.

Core audit flagged this as the #2 CRITICAL weakness. Fix D
adds two accessors on ``UnifiedMemory``:

  * ``get_brain_memory()`` — returns the 6-layer
    ``IntelligentMemory`` backend instance
  * ``get_memory_intelligence()`` — returns the 4-level
    ``MemoryIntelligence`` backend instance

And updates ``DecisionBrain._init_components`` and
``DecisionEngine._get_memory`` / ``_get_intelligence`` to
call the unified accessors instead of direct imports.

These tests pin the new contract and AST-check that the
brain files don't regress to direct imports.
"""
from __future__ import annotations

import pytest


class TestUnifiedMemoryAccessors:
    def test_get_brain_memory_returns_intelligent_memory(self):
        """UnifiedMemory.get_brain_memory() must return an
        IntelligentMemory instance (or None if backend failed
        to load)."""
        from core.memory.unified_memory import get_unified_memory
        from core.brain.memory import IntelligentMemory
        um = get_unified_memory()
        um.initialize()
        brain = um.get_brain_memory()
        assert brain is not None
        assert isinstance(brain, IntelligentMemory)

    def test_get_memory_intelligence_returns_memory_intelligence(self):
        from core.memory.unified_memory import get_unified_memory
        from core.memory.intelligence import MemoryIntelligence
        um = get_unified_memory()
        um.initialize()
        mi = um.get_memory_intelligence()
        assert mi is not None
        assert isinstance(mi, MemoryIntelligence)

    def test_accessors_auto_initialize(self):
        """Calling get_brain_memory() on a fresh
        UnifiedMemory must lazily initialise — callers
        shouldn't have to call initialize() first."""
        from core.memory.unified_memory import UnifiedMemory
        um = UnifiedMemory()
        # Don't call initialize() manually; the accessor
        # should do it for us
        brain = um.get_brain_memory()
        # Either it loaded or it explicitly reports failure
        # via get_init_errors — never crash
        assert brain is not None or "brain_memory" in um.get_init_errors()

    def test_same_instance_across_calls(self):
        """Multiple calls to the accessor must return the
        SAME underlying instance so callers don't accidentally
        operate on parallel objects."""
        from core.memory.unified_memory import get_unified_memory
        um = get_unified_memory()
        um.initialize()
        a = um.get_brain_memory()
        b = um.get_brain_memory()
        assert a is b


class TestDecisionBrainUsesUnifiedAccess:
    def test_brain_memory_comes_from_unified(self):
        """DecisionBrain._brain_memory must be the same
        instance UnifiedMemory.get_brain_memory() returns —
        proof that the brain is going through the unified
        entry point and not a parallel import."""
        from core.memory.unified_memory import get_unified_memory
        from core.brain.decision_brain import DecisionBrain

        um = get_unified_memory()
        um.initialize()
        expected = um.get_brain_memory()

        brain = DecisionBrain()
        brain._init_components()

        assert brain._brain_memory is expected, (
            "DecisionBrain._brain_memory must come from "
            "UnifiedMemory.get_brain_memory(), not a direct "
            "import of core.brain.memory"
        )

    def test_memory_intel_comes_from_unified(self):
        from core.memory.unified_memory import get_unified_memory
        from core.brain.decision_brain import DecisionBrain

        um = get_unified_memory()
        um.initialize()
        expected = um.get_memory_intelligence()

        brain = DecisionBrain()
        brain._init_components()

        assert brain._memory_intel is expected


class TestDecisionEngineUsesUnifiedAccess:
    def test_engine_memory_comes_from_unified(self):
        from core.memory.unified_memory import get_unified_memory
        from core.brain.decision_engine import DecisionEngine

        um = get_unified_memory()
        um.initialize()
        expected = um.get_brain_memory()

        engine = DecisionEngine()
        got = engine._get_memory()

        assert got is expected

    def test_engine_intelligence_comes_from_unified(self):
        from core.memory.unified_memory import get_unified_memory
        from core.brain.decision_engine import DecisionEngine

        um = get_unified_memory()
        um.initialize()
        expected = um.get_memory_intelligence()

        engine = DecisionEngine()
        got = engine._get_intelligence()

        assert got is expected


class TestNoDirectBrainMemoryImportsInCoreBrain:
    """AST-level regression: the key brain files must NOT
    re-introduce direct imports of
    ``core.brain.memory.get_brain_memory`` or
    ``core.memory.intelligence.get_memory_intelligence``.
    Fix D established the rule that these backends are
    accessed exclusively through ``UnifiedMemory``.

    ``core/brain/memory.py`` itself is allowed to define
    ``get_brain_memory`` (it's the canonical implementation).
    ``core/memory/unified_memory.py`` is allowed to import
    it internally (it wraps the backend).
    """

    _ALLOWED_FILES = {
        "core/brain/memory.py",        # defines get_brain_memory
        "core/memory/unified_memory.py",  # wraps the backend
        "core/memory/intelligence.py",     # defines get_memory_intelligence
        # Learning / legacy pathways that haven't been
        # migrated yet — document them explicitly so this
        # list shrinks over time.
        "core/brain/learning_loop.py",
        "core/brain/learning_model.py",
    }

    def _find_offenders(self, target: str) -> list[str]:
        """Walk core/brain and core/autonomous for files that
        contain the forbidden import pattern."""
        import pathlib
        import re
        root = pathlib.Path("core")
        offenders: list[str] = []
        pattern = re.compile(
            rf"from\s+{re.escape(target)}\s+import",
        )
        for folder in ("brain", "autonomous"):
            search_root = root / folder
            if not search_root.exists():
                continue
            for py in search_root.rglob("*.py"):
                rel = str(py)
                if any(rel.endswith(a) for a in self._ALLOWED_FILES):
                    continue
                try:
                    text = py.read_text(encoding="utf-8")
                except Exception:
                    continue
                if pattern.search(text):
                    offenders.append(rel)
        return offenders

    def test_decision_brain_does_not_import_brain_memory_directly(self):
        import pathlib, re
        path = pathlib.Path("core/brain/decision_brain.py")
        text = path.read_text(encoding="utf-8")
        # Must NOT contain ``from core.brain.memory import``
        assert not re.search(
            r"from\s+core\.brain\.memory\s+import",
            text,
        ), (
            "decision_brain.py still imports from core.brain.memory "
            "directly — route through UnifiedMemory.get_brain_memory()"
        )

    def test_decision_engine_does_not_import_brain_memory_directly(self):
        import pathlib, re
        path = pathlib.Path("core/brain/decision_engine.py")
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"from\s+core\.brain\.memory\s+import",
            text,
        ), (
            "decision_engine.py still imports from core.brain.memory "
            "directly — route through UnifiedMemory.get_brain_memory()"
        )

    def test_decision_engine_does_not_import_memory_intelligence_directly(self):
        import pathlib, re
        path = pathlib.Path("core/brain/decision_engine.py")
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"from\s+core\.memory\.intelligence\s+import",
            text,
        ), (
            "decision_engine.py still imports from core.memory.intelligence "
            "directly — route through UnifiedMemory.get_memory_intelligence()"
        )

    def test_decision_brain_does_not_import_memory_intelligence_directly(self):
        import pathlib, re
        path = pathlib.Path("core/brain/decision_brain.py")
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"from\s+core\.memory\.intelligence\s+import",
            text,
        ), (
            "decision_brain.py still imports from core.memory.intelligence "
            "directly — route through UnifiedMemory.get_memory_intelligence()"
        )


class TestBackwardsCompatWithLegacyImports:
    """``core.brain.memory.get_brain_memory`` and
    ``core.memory.intelligence.get_memory_intelligence``
    are still allowed to exist as the canonical
    implementations — we only routed brain callers through
    UnifiedMemory. Tests that import them directly (for
    isolated fixture purposes) must still work."""

    def test_brain_memory_module_still_exposes_function(self):
        from core.brain.memory import get_brain_memory
        assert callable(get_brain_memory)
        instance = get_brain_memory()
        assert instance is not None

    def test_memory_intelligence_module_still_exposes_function(self):
        from core.memory.intelligence import get_memory_intelligence
        assert callable(get_memory_intelligence)
        instance = get_memory_intelligence()
        assert instance is not None

    def test_singletons_match_unified_accessors(self):
        """``get_brain_memory()`` (direct import) and
        ``UnifiedMemory.get_brain_memory()`` must return the
        SAME instance — otherwise the "two parallel DBs"
        problem has just been renamed, not fixed."""
        from core.brain.memory import get_brain_memory as direct_brain
        from core.memory.intelligence import get_memory_intelligence as direct_mi
        from core.memory.unified_memory import get_unified_memory

        um = get_unified_memory()
        um.initialize()

        assert direct_brain() is um.get_brain_memory(), (
            "direct get_brain_memory() and unified accessor "
            "return different instances — there are still two "
            "parallel memory systems"
        )
        assert direct_mi() is um.get_memory_intelligence(), (
            "direct get_memory_intelligence() and unified "
            "accessor return different instances"
        )
