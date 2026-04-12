"""Wave 12 tests — DCLP (Double-Checked Locking Pattern) for remaining singletons.

Verifies that 11 additional singleton getters across core/ and engines/
now use thread-safe DCLP to prevent duplicate instantiation under
concurrent access.

Each test:
1. Imports the module and its getter function
2. Verifies the module has a ``_*_lock`` or ``_instance_lock`` at module level
3. Spawns 4 threads through a barrier to race on the getter
4. Asserts all threads received the exact same object (``is`` check)
"""
from __future__ import annotations

import threading
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _race_getter(getter, count: int = 4) -> list[Any]:
    """Run *getter* from *count* threads simultaneously and return
    the list of objects each thread received."""
    barrier = threading.Barrier(count)
    results: list[Any] = [None] * count
    errors: list[Exception] = []

    def worker(idx: int):
        try:
            barrier.wait(timeout=5)
            results[idx] = getter()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors, f"Thread errors: {errors}"
    return results


# ---------------------------------------------------------------------------
# Per-module tests
# ---------------------------------------------------------------------------


class TestExperienceDCLP:
    def test_has_lock(self):
        import core.ai.experience as mod
        assert hasattr(mod, "_experience_lock")

    def test_thread_safe_singleton(self):
        from core.ai.experience import get_experience
        objs = _race_getter(get_experience)
        assert all(o is objs[0] for o in objs)


class TestNotificationsDCLP:
    def test_has_lock(self):
        import core.system.notifications as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.system.notifications import get_notifications
        objs = _race_getter(get_notifications)
        assert all(o is objs[0] for o in objs)


class TestAutoSchedulerDCLP:
    def test_has_lock(self):
        import core.system.auto_scheduler as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.system.auto_scheduler import get_scheduler
        objs = _race_getter(get_scheduler)
        assert all(o is objs[0] for o in objs)


class TestModelRouterDCLP:
    def test_has_lock(self):
        import core.system.model_router as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.system.model_router import get_model_router
        objs = _race_getter(get_model_router)
        assert all(o is objs[0] for o in objs)


class TestProductionSingletonsDCLP:
    """production.py has 5 singleton getters — test each."""

    GETTERS = [
        "get_config",
        "get_rate_limiter",
        "get_error_recovery",
        "get_backup",
        "get_audit",
    ]

    LOCKS = [
        "_config_lock",
        "_rate_limiter_lock",
        "_recovery_lock",
        "_backup_lock",
        "_audit_lock",
    ]

    def test_has_locks(self):
        import core.system.production as mod
        for lock_name in self.LOCKS:
            assert hasattr(mod, lock_name), f"Missing {lock_name}"

    @pytest.mark.parametrize("getter_name", GETTERS)
    def test_thread_safe_singleton(self, getter_name: str):
        import core.system.production as mod
        getter = getattr(mod, getter_name)
        objs = _race_getter(getter)
        assert all(o is objs[0] for o in objs)


class TestAlertSystemDCLP:
    def test_has_lock(self):
        import core.system.alerts as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.system.alerts import get_alert_system
        objs = _race_getter(get_alert_system)
        assert all(o is objs[0] for o in objs)


class TestStrategyPlannerDCLP:
    def test_has_lock(self):
        import core.brain.strategy_planner as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.brain.strategy_planner import get_strategy_planner
        objs = _race_getter(get_strategy_planner)
        assert all(o is objs[0] for o in objs)


class TestHealthMonitorDCLP:
    def test_has_lock(self):
        import core.system.health_monitor as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.system.health_monitor import get_health_monitor
        objs = _race_getter(get_health_monitor)
        assert all(o is objs[0] for o in objs)


class TestModelWorkersDCLP:
    def test_has_lock(self):
        import core.system.model_workers as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.system.model_workers import get_model_workers
        objs = _race_getter(get_model_workers)
        assert all(o is objs[0] for o in objs)


class TestCopywriterDCLP:
    def test_has_lock(self):
        import core.ai.copywriter as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.ai.copywriter import get_copywriter
        objs = _race_getter(get_copywriter)
        assert all(o is objs[0] for o in objs)


class TestPolicyStoreDCLP:
    def test_has_lock(self):
        import engines.meta_governance.policy_store as mod
        assert hasattr(mod, "_default_store_lock")

    def test_thread_safe_singleton(self):
        from engines.meta_governance.policy_store import (
            get_default_store,
            reset_default_store,
        )
        reset_default_store()
        objs = _race_getter(get_default_store)
        assert all(o is objs[0] for o in objs)
        reset_default_store()
