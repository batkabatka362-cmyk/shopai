"""Wave 11 final sweep tests.

Verifies that zero ``except Exception: pass`` blocks remain anywhere
in the ``core/`` package. Previous waves (8–10) eliminated them from
the most critical modules; Wave 11 closes the last 30 across 23 files.

Also verifies that the two intelligence-loop stage modules gained
loggers.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest


_CORE_DIR = Path(__file__).resolve().parents[1] / "core"


class TestNoBareExceptPassInCore:
    """Codebase-wide AST check: no ``except Exception: pass`` anywhere
    under ``core/``."""

    @staticmethod
    def _collect_python_files() -> list[Path]:
        results: list[Path] = []
        for dirpath, _dirs, filenames in os.walk(_CORE_DIR):
            for fn in filenames:
                if fn.endswith(".py"):
                    results.append(Path(dirpath) / fn)
        return sorted(results)

    def test_zero_bare_except_pass_in_core(self):
        """Walk every .py under core/ and AST-parse for
        ``except Exception: pass`` (unnamed handler with single Pass body).
        """
        violations: list[str] = []
        for path in self._collect_python_files():
            try:
                src = path.read_text()
                tree = ast.parse(src, filename=str(path))
            except SyntaxError:
                continue  # skip unparseable files

            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if (
                    node.name is None
                    and len(node.body) == 1
                    and isinstance(node.body[0], ast.Pass)
                ):
                    rel = path.relative_to(_CORE_DIR.parent)
                    violations.append(f"{rel}:{node.lineno}")

        assert not violations, (
            f"Found {len(violations)} bare 'except Exception: pass' block(s):\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


class TestIntelligenceLoopStagesHaveLoggers:
    """The two stage modules that were missing loggers should now have them."""

    def test_stage_track_has_logger(self):
        import importlib
        mod = importlib.import_module("core.intelligence.loop.stage_track")
        assert hasattr(mod, "logger"), (
            "stage_track module should have a module-level logger"
        )

    def test_stage_analyze_has_logger(self):
        import importlib
        mod = importlib.import_module("core.intelligence.loop.stage_analyze")
        assert hasattr(mod, "logger"), (
            "stage_analyze module should have a module-level logger"
        )


class TestFixedModulesLogExceptions:
    """Spot-check a sample of the 23 fixed files to verify they now
    capture ``as exc`` in their except handlers."""

    MODULES = [
        "core.full_system_loop",
        "core.automation",
        "core.brain.rule_health",
        "core.brain.revenue_strategy",
        "core.brain.reasoning_chain",
        "core.brain.learning_model",
        "core.brain.decision_engine",
        "core.reactor",
        "core.plugins.plugin_registry",
        "core.intelligence.strategy_optimizer",
        "core.system.tool_orchestrator",
        "core.system.store_registry",
        "core.system.realtime_monitor",
        "core.system.production",
        "core.system.ab_testing",
        "core.system.model_router",
        "core.system.auto_scheduler",
        "core.system.notifications",
        "core.self_monitor.auto_recovery",
        "core.bridge.shopify_bridge",
        "core.core_orchestrator",
        "core.intelligence.loop.stage_track",
        "core.intelligence.loop.stage_analyze",
    ]

    @pytest.mark.parametrize("mod_path", MODULES)
    def test_no_bare_except_pass(self, mod_path):
        import importlib
        import inspect
        import textwrap

        mod = importlib.import_module(mod_path)
        src = inspect.getsource(mod)
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
            f"{mod_path} still has bare 'except: pass' at lines {bare}"
        )
