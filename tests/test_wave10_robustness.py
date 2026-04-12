"""Wave 10 robustness tests.

Covers three improvements:

  1. Thread-safe singleton accessors (DCLP round 2) for 8 additional
     high-traffic modules.
  2. Silent ``except Exception: pass`` eliminated from dashboard_api,
     llm_cache, and server — all now log via logger.debug/warning.
  3. DB connection leak fix in migrations.py (conn.close in finally).
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
# 1. Thread-safe singletons (round 2) — 8 new modules
# ===================================================================


class TestThreadSafeSingletonsRound2:
    """Verify DCLP pattern on 8 additional singletons added in Wave 10."""

    SINGLETONS = [
        ("core.data.architecture", "get_data_architecture", "_instance", "_instance_lock"),
        ("core.system.llm_adapter", "get_llm", "_instance", "_instance_lock"),
        ("core.ai.reasoning", "ai_reason", "_instance", "_instance_lock"),
        ("core.system.store_registry", "get_store_registry", "_instance", "_instance_lock"),
        ("core.system.llm_cache", "get_llm_cache", "_instance", "_instance_lock"),
        ("core.system.webhook_handler", "get_webhook_handler", "_instance", "_instance_lock"),
        ("core.memory.similarity_search", "get_similarity_search", "_instance", "_instance_lock"),
        ("core.intelligence_cycle", "get_intelligence_cycle", "_instance", "_instance_lock"),
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
        """The DCLP pattern requires TWO ``is None`` checks — one
        outside the lock (fast path) and one inside."""
        import importlib
        mod = importlib.import_module(mod_path)
        fn = getattr(mod, func_name)
        src = inspect.getsource(fn)
        count = src.count("is None")
        assert count >= 2, (
            f"{func_name} has {count} 'is None' checks, need >=2 for DCLP"
        )

    def test_data_architecture_returns_same_instance_across_threads(self):
        """Concurrent calls to get_data_architecture must return the
        same instance (no double-init race)."""
        from core.data import architecture as mod

        original = mod._instance
        mod._instance = None

        results: list[Any] = []
        barrier = threading.Barrier(4)

        def _get():
            barrier.wait()
            results.append(mod.get_data_architecture())

        threads = [threading.Thread(target=_get) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4
        assert all(r is results[0] for r in results)

        mod._instance = original

    def test_llm_cache_returns_same_instance_across_threads(self):
        from core.system import llm_cache as mod

        original = mod._instance
        mod._instance = None

        results: list[Any] = []
        barrier = threading.Barrier(4)

        def _get():
            barrier.wait()
            results.append(mod.get_llm_cache())

        threads = [threading.Thread(target=_get) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 4
        assert all(r is results[0] for r in results)

        mod._instance = original


# ===================================================================
# 2. No bare except:pass in dashboard_api
# ===================================================================


class TestDashboardApiNoBareExceptPass:
    """AST-level check: ``api.dashboard_api.DashboardAPIHandler``
    must not contain any bare ``except Exception: pass`` handlers."""

    def test_no_bare_except_pass(self):
        from api.dashboard_api import DashboardAPIHandler

        src = textwrap.dedent(inspect.getsource(DashboardAPIHandler))
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
            f"DashboardAPIHandler still has bare 'except: pass' "
            f"at relative lines {bare}"
        )

    def test_all_except_handlers_capture_exc_variable(self):
        """Every except handler in DashboardAPIHandler should capture
        the exception as a named variable (``as exc``)."""
        from api.dashboard_api import DashboardAPIHandler

        src = textwrap.dedent(inspect.getsource(DashboardAPIHandler))
        tree = ast.parse(src)

        unnamed: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # Allow bare except clauses for TypeError/ValueError
                # that are purely control-flow (e.g. int() parsing).
                if node.type and hasattr(node.type, 'id'):
                    if node.type.id in ("TypeError", "ValueError"):
                        continue
                if node.type and hasattr(node.type, 'elts'):
                    # Tuple of exception types
                    names = [getattr(e, 'id', '') for e in node.type.elts]
                    if all(n in ("TypeError", "ValueError") for n in names):
                        continue
                if node.name is None:
                    unnamed.append(node.lineno)

        assert not unnamed, (
            f"DashboardAPIHandler has unnamed except handlers "
            f"at relative lines {unnamed}"
        )


# ===================================================================
# 3. API server routes log errors before returning 500
# ===================================================================


class TestServerApiLogging:
    """Verify api/server.py error handlers include logger.warning calls."""

    def test_server_error_handlers_log_before_500(self):
        """Every except block in the API server that returns a 500
        should also call logger.warning."""
        from api import server as mod

        src = inspect.getsource(mod)

        # Find all except blocks that contain '_json_response(500'
        import re
        # Pattern: except ... as exc: ... _json_response(500 ...
        # We want to ensure logger.warning appears between except and the response
        blocks = re.findall(
            r'except\s+Exception\s+as\s+exc:.*?(?=except|def\s|\Z)',
            src,
            re.DOTALL,
        )
        returns_500 = [b for b in blocks if '_json_response(500' in b]
        missing_log = [b for b in returns_500 if 'logger.warning' not in b]

        assert not missing_log, (
            f"Found {len(missing_log)} error handler(s) returning 500 "
            f"without logger.warning"
        )


# ===================================================================
# 4. LLM cache logger exists
# ===================================================================


class TestLLMCacheLogging:
    """Verify llm_cache.py now has a logger and uses it."""

    def test_llm_cache_has_logger(self):
        from core.system import llm_cache
        assert hasattr(llm_cache, 'logger'), (
            "llm_cache module should have a 'logger' attribute"
        )

    def test_cached_ask_logs_serialisation_failure(self):
        """When context serialisation fails, it should log at debug level."""
        src = inspect.getsource(__import__('core.system.llm_cache', fromlist=['cached_ask']))
        assert 'logger.debug' in src, (
            "llm_cache should contain at least one logger.debug call"
        )


# ===================================================================
# 5. migrations.py connection leak fix
# ===================================================================


class TestMigrationsConnLeak:
    """Verify that get_migration_status uses finally to close connections."""

    def test_conn_close_in_finally_block(self):
        from core.db import migrations

        src = inspect.getsource(migrations)
        tree = ast.parse(src)

        # Find the function get_all_schema_info (contains the conn logic)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_all_schema_info":
                func_src = ast.get_source_segment(src, node)
                if func_src is None:
                    func_src = inspect.getsource(
                        getattr(migrations, 'get_all_schema_info')
                    )
                assert 'finally' in func_src, (
                    "get_all_schema_info should use a finally block "
                    "to ensure conn.close()"
                )
                assert 'conn.close()' in func_src, (
                    "get_all_schema_info should call conn.close() in finally"
                )
                return

        pytest.fail("get_all_schema_info function not found in migrations module")
