"""Regression tests for Fix E: strategy module consolidation.

Core audit originally recommended merging the three
strategy modules (``strategy_planner.py`` +
``strategy_expander.py`` + ``revenue_strategy.py``) into
one file with ~8 hours of effort. On second review the
three modules DO have distinct responsibilities:

  * ``strategy_planner.py`` — memory-driven (history → plans)
  * ``strategy_expander.py`` — coverage-driven (fills gaps)
  * ``revenue_strategy.py`` — state-driven (current phase)

A merge would be scope creep for LOW reward. Instead Fix E
applies the Fix D unified-memory pattern to the two
modules that access memory directly and adds explicit
division-of-labor header docs to all three so the next
engineer to touch them sees the boundary.

These tests pin:

  1. ``strategy_planner`` routes through UnifiedMemory.
  2. ``strategy_expander`` routes through UnifiedMemory.
  3. ``revenue_strategy`` doesn't touch memory (state-only).
  4. Each file carries the division-of-labor header doc.
  5. AST regex guard: no direct
     ``from core.memory.intelligence import`` in any of the
     three files.
"""
from __future__ import annotations

import pytest


class TestStrategyPlannerUsesUnifiedMemory:
    def test_planner_memory_comes_from_unified(self):
        from core.memory.unified_memory import get_unified_memory
        from core.brain.strategy_planner import StrategyPlanner

        um = get_unified_memory()
        um.initialize()
        expected = um.get_memory_intelligence()

        planner = StrategyPlanner()
        planner._ensure_init()

        assert planner._memory_intel is expected, (
            "strategy_planner._memory_intel must come from "
            "UnifiedMemory.get_memory_intelligence(), not a "
            "direct import of core.memory.intelligence"
        )


class TestStrategyExpanderUsesUnifiedMemory:
    def test_expander_routes_through_unified(self, monkeypatch):
        """The expander's ``expand()`` method must pull its
        memory backend via ``UnifiedMemory.get_memory_intelligence()``.

        We verify this by tracking which import path is hit:
        if the expander calls ``get_unified_memory()`` then
        our monkey-patched version fires; if it still calls
        the legacy direct import, the test would pass
        falsely, so we also assert via the AST guard below.
        """
        from core.brain.strategy_expander import StrategyExpander

        hit_count = {"unified": 0}
        import core.memory.unified_memory as um_mod
        original = um_mod.get_unified_memory

        def _tracking():
            hit_count["unified"] += 1
            return original()

        monkeypatch.setattr(um_mod, "get_unified_memory", _tracking)

        expander = StrategyExpander()
        expander.expand()

        assert hit_count["unified"] >= 1, (
            "expander.expand() did not call "
            "get_unified_memory() — it must route through "
            "the unified entry point"
        )


class TestRevenueStrategyIsStateOnly:
    def test_revenue_strategy_does_not_import_memory(self):
        """``revenue_strategy.py`` is state-driven — it
        should NOT touch the memory layer at all. Any import
        from ``core.memory`` or ``core.brain.memory`` would
        mean the module has grown beyond its stated scope."""
        import pathlib, re
        path = pathlib.Path("core/brain/revenue_strategy.py")
        text = path.read_text(encoding="utf-8")
        assert not re.search(
            r"from\s+core\.memory(\.|\s+import)",
            text,
        )
        assert not re.search(
            r"from\s+core\.brain\.memory\s+import",
            text,
        )

    def test_revenue_strategy_still_produces_plan(self):
        from core.brain.revenue_strategy import RevenueStrategy
        rs = RevenueStrategy()
        plan = rs.create_plan([{"id": "p1", "price": 10}], [], [])
        assert plan.get("phase") in ("launch", "growth", "scale")
        assert "strategies" in plan


class TestStrategyModulesHaveDivisionOfLaborDocs:
    """The three files should carry explicit header docs
    stating which module owns which axis of strategy work.
    This pins the scope decision Fix E made (not merging)
    so the next engineer to touch the files sees the
    distinction."""

    def test_strategy_planner_has_division_doc(self):
        import pathlib
        text = pathlib.Path("core/brain/strategy_planner.py").read_text(
            encoding="utf-8",
        )
        assert "memory-driven" in text
        assert "coverage-driven" in text
        assert "state-driven" in text

    def test_strategy_expander_has_division_doc(self):
        import pathlib
        text = pathlib.Path("core/brain/strategy_expander.py").read_text(
            encoding="utf-8",
        )
        assert "coverage-driven" in text

    def test_revenue_strategy_has_division_doc(self):
        import pathlib
        text = pathlib.Path("core/brain/revenue_strategy.py").read_text(
            encoding="utf-8",
        )
        assert "state-driven" in text


class TestNoDirectMemoryIntelligenceImportsInStrategyModules:
    """AST-level regression guard: none of the three
    strategy modules may contain a direct
    ``from core.memory.intelligence import get_memory_intelligence``
    after Fix E. Memory access is unified through
    ``UnifiedMemory.get_memory_intelligence()`` only."""

    def test_planner_has_no_direct_import(self):
        import pathlib, re
        text = pathlib.Path("core/brain/strategy_planner.py").read_text(
            encoding="utf-8",
        )
        assert not re.search(
            r"from\s+core\.memory\.intelligence\s+import\s+get_memory_intelligence",
            text,
        )

    def test_expander_has_no_direct_import(self):
        import pathlib, re
        text = pathlib.Path("core/brain/strategy_expander.py").read_text(
            encoding="utf-8",
        )
        assert not re.search(
            r"from\s+core\.memory\.intelligence\s+import\s+get_memory_intelligence",
            text,
        )


class TestBackwardsCompatForController:
    """The controller still imports the same public
    functions from these modules — the migration is
    internal-only, no signature changes."""

    def test_strategy_planner_factory_still_exposed(self):
        from core.brain.strategy_planner import get_strategy_planner
        instance = get_strategy_planner()
        assert instance is not None

    def test_strategy_expander_factory_still_exposed(self):
        from core.brain.strategy_expander import get_strategy_expander
        instance = get_strategy_expander()
        assert instance is not None

    def test_revenue_strategy_class_still_exposed(self):
        from core.brain.revenue_strategy import RevenueStrategy
        instance = RevenueStrategy()
        assert instance is not None
