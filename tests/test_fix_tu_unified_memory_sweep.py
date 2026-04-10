"""Regression guard for Fix T+U: no direct memory
intelligence or brain memory imports remain in the brain
core or controller.

Fixes D/I/R routed individual files through UnifiedMemory
but left several files in core/brain/ and controller.py
still importing directly. Fix T+U sweeps the remaining
violations so ALL brain-core memory access goes through
the single UnifiedMemory entry point.

This test pins the invariant: any future file that needs
MemoryIntelligence or IntelligentMemory from core/brain/
or core/autonomous/ must route through UnifiedMemory.
"""
from __future__ import annotations

import pathlib
import re

import pytest


_BRAIN_DIR = pathlib.Path("core/brain")
_CONTROLLER = pathlib.Path("core/autonomous/controller.py")
_BYPASS_WHITELIST = {"core/memory/unified_memory.py", "core/memory/similarity_search.py"}

_DIRECT_BRAIN_MEM = re.compile(
    r"from\s+core\.brain\.memory\s+import\s+get_brain_memory",
)
_DIRECT_INTEL = re.compile(
    r"from\s+core\.memory\.intelligence\s+import\s+get_memory_intelligence",
)


class TestNoDirectMemoryImportsInBrain:
    def test_no_direct_get_brain_memory_in_brain(self):
        for py in _BRAIN_DIR.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            assert not _DIRECT_BRAIN_MEM.search(text), (
                f"{py} still imports get_brain_memory directly — "
                f"route through UnifiedMemory"
            )

    def test_no_direct_get_memory_intelligence_in_brain(self):
        for py in _BRAIN_DIR.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            assert not _DIRECT_INTEL.search(text), (
                f"{py} still imports get_memory_intelligence "
                f"directly — route through UnifiedMemory"
            )

    def test_no_direct_get_memory_intelligence_in_controller(self):
        text = _CONTROLLER.read_text(encoding="utf-8")
        assert not _DIRECT_INTEL.search(text), (
            "controller.py still imports get_memory_intelligence "
            "directly — route through UnifiedMemory"
        )
