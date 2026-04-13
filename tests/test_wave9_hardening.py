"""Wave 9 hardening tests.

Covers two improvements:

  1. Silent ``except Exception: pass`` blocks replaced with
     ``logger.debug/warning(...)`` across controller, system,
     brain, and AI modules.
  2. Thread-safe singleton accessors for memory, brain,
     cognitive, and mind modules (DCLP pattern).
"""
from __future__ import annotations

import ast
import inspect
import textwrap
import threading
from typing import Any
from unittest.mock import patch

import pytest


# ===================================================================
# 1. No remaining bare except:pass in critical modules
# ===================================================================


class TestNoBareExceptPass:
    """AST-level check: targeted modules must not contain any
    bare ``except Exception: pass`` handlers."""

    MODULES = [
        ("core.system.data_middleware", "DataFirstMiddleware"),
        ("core.system.webhook_handler", "WebhookHandler"),
        ("core.system.model_workers", "ModelWorkerSystem"),
        ("core.system.structured_logger", "StructuredLogger"),
        ("core.brain.decision_brain", "DecisionBrain"),
        ("core.brain.strategy_planner", "StrategyPlanner"),
    ]

    @pytest.mark.parametrize("mod_path,cls_name", MODULES)
    def test_no_bare_except_pass(self, mod_path, cls_name):
        import importlib
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name)
        src = textwrap.dedent(inspect.getsource(cls))
        tree = ast.parse(src)

        bare: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if (
                    node.name is None
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)
                ):
                    bare.append(node.lineno)

        assert not bare, (
            f"{cls_name} still has bare 'except: pass' at relative lines {bare}"
        )

    def test_controller_learning_pipeline_no_bare_pass(self):
        from core.autonomous.controller import LearningPipeline

        src = textwrap.dedent(inspect.getsource(LearningPipeline))
        tree = ast.parse(src)

        bare: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if (
                    node.name is None
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)
                ):
                    bare.append(node.lineno)

        assert not bare, (
            f"LearningPipeline still has bare 'except: pass' at relative lines {bare}"
        )

    def test_product_finder_no_bare_pass(self):
        from core.ai.product_finder import AIProductFinder

        src = textwrap.dedent(inspect.getsource(AIProductFinder))
        tree = ast.parse(src)

        bare: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if (
                    node.name is None
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)
                ):
                    bare.append(node.lineno)

        assert not bare, (
            f"AIProductFinder still has bare 'except: pass' at relative lines {bare}"
        )

    def test_self_improver_no_bare_pass(self):
        from core.ai.self_improver import SelfImprover

        src = textwrap.dedent(inspect.getsource(SelfImprover))
        tree = ast.parse(src)

        bare: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if (
                    node.name is None
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)
                ):
                    bare.append(node.lineno)

        assert not bare, (
            f"SelfImprover still has bare 'except: pass' at relative lines {bare}"
        )


# ===================================================================
# 2. Thread-safe singletons
# ===================================================================


class TestThreadSafeSingletons:
    """Critical singletons use DCLP (double-checked locking pattern)
    with threading.Lock to prevent race-condition double init."""

    SINGLETONS = [
        ("core.brain.memory", "get_brain_memory", "_instance", "_instance_lock"),
        ("core.memory.intelligence", "get_memory_intelligence", "_instance", "_instance_lock"),
        ("core.brain.cognitive", "get_cognitive_module", "_instance", "_instance_lock"),
        ("core.cognitive.mind", "get_mind", "_instance", "_instance_lock"),
    ]

    @pytest.mark.parametrize("mod_path,func_name,inst_var,lock_var", SINGLETONS)
    def test_lock_exists(self, mod_path, func_name, inst_var, lock_var):
        import importlib
        mod = importlib.import_module(mod_path)
        lock = getattr(mod, lock_var, None)
        assert lock is not None, f"{mod_path}.{lock_var} not found"
        assert isinstance(lock, type(threading.Lock())), (
            f"{mod_path}.{lock_var} is not a threading.Lock"
        )

    @pytest.mark.parametrize("mod_path,func_name,inst_var,lock_var", SINGLETONS)
    def test_getter_uses_lock_in_source(self, mod_path, func_name, inst_var, lock_var):
        import importlib
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, func_name)
        src = inspect.getsource(fn)
        assert lock_var in src, (
            f"{func_name} does not reference {lock_var}"
        )
        assert "with" in src, (
            f"{func_name} does not use 'with' statement for lock"
        )

    @pytest.mark.parametrize("mod_path,func_name,inst_var,lock_var", SINGLETONS)
    def test_double_checked_pattern(self, mod_path, func_name, inst_var, lock_var):
        """The DCLP pattern requires TWO `is None` checks — one
        outside the lock (fast path) and one inside."""
        import importlib
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, func_name)
        src = inspect.getsource(fn)
        # Count occurrences of "is None"
        count = src.count("is None")
        assert count >= 2, (
            f"{func_name} has {count} 'is None' checks, need >=2 for DCLP"
        )

    def test_brain_memory_returns_same_instance_across_threads(self):
        """Concurrent calls to get_brain_memory must return the
        same instance (no double-init race)."""
        from core.brain import memory as mem_mod

        # Reset singleton
        original = mem_mod._instance
        mem_mod._instance = None

        results: list[Any] = []
        barrier = threading.Barrier(4)

        def _get():
            barrier.wait()
            results.append(mem_mod.get_brain_memory())

        threads = [threading.Thread(target=_get) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should get the same instance
        assert len(results) == 4
        assert all(r is results[0] for r in results)

        # Restore
        mem_mod._instance = original

    def test_cognitive_module_returns_same_instance_across_threads(self):
        from core.brain import cognitive as cog_mod

        original = cog_mod._instance
        cog_mod._instance = None

        results: list[Any] = []
        barrier = threading.Barrier(4)

        def _get():
            barrier.wait()
            results.append(cog_mod.get_cognitive_module())

        threads = [threading.Thread(target=_get) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4
        assert all(r is results[0] for r in results)

        cog_mod._instance = original
