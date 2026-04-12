"""Wave 12 tests — DCLP (Double-Checked Locking Pattern) for remaining singletons.

Verifies that 28 additional singleton getters across core/ and engines/
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


# ---------------------------------------------------------------------------
# Wave 12b — 14 more files, 17 more singletons
# ---------------------------------------------------------------------------


class TestCustomerJourneyDCLP:
    def test_has_lock(self):
        import core.ai.customer_journey as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.ai.customer_journey import get_customer_journey
        objs = _race_getter(get_customer_journey)
        assert all(o is objs[0] for o in objs)


class TestExternalToolsDCLP:
    def test_has_lock(self):
        import core.ai.external_tools as mod
        assert hasattr(mod, "_tools_lock")

    def test_thread_safe_singleton(self):
        from core.ai.external_tools import get_tools
        objs = _race_getter(get_tools)
        assert all(o is objs[0] for o in objs)


class TestInventoryPredictorDCLP:
    def test_has_lock(self):
        import core.ai.inventory_predictor as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.ai.inventory_predictor import get_inventory_predictor
        objs = _race_getter(get_inventory_predictor)
        assert all(o is objs[0] for o in objs)


class TestProductFinderDCLP:
    def test_has_lock(self):
        import core.ai.product_finder as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.ai.product_finder import get_product_finder
        objs = _race_getter(get_product_finder)
        assert all(o is objs[0] for o in objs)


class TestSmartPricingDCLP:
    def test_has_lock(self):
        import core.ai.smart_pricing as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.ai.smart_pricing import get_smart_pricing
        objs = _race_getter(get_smart_pricing)
        assert all(o is objs[0] for o in objs)


class TestStoreDoctorDCLP:
    def test_has_lock(self):
        import core.ai.store_doctor as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.ai.store_doctor import get_store_doctor
        objs = _race_getter(get_store_doctor)
        assert all(o is objs[0] for o in objs)


class TestCompetitiveIntelDCLP:
    def test_has_lock(self):
        import core.brain.competitive_intel as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.brain.competitive_intel import get_competitive_intelligence
        objs = _race_getter(get_competitive_intelligence)
        assert all(o is objs[0] for o in objs)


class TestMultiStoreBrainDCLP:
    def test_has_lock(self):
        import core.brain.multi_store_brain as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.brain.multi_store_brain import get_multi_store
        objs = _race_getter(get_multi_store)
        assert all(o is objs[0] for o in objs)


class TestRevenueStrategyDCLP:
    def test_has_lock(self):
        import core.brain.revenue_strategy as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.brain.revenue_strategy import get_revenue_strategy
        objs = _race_getter(get_revenue_strategy)
        assert all(o is objs[0] for o in objs)


class TestRuleHealthDCLP:
    def test_has_lock(self):
        import core.brain.rule_health as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.brain.rule_health import get_rule_health_checker
        objs = _race_getter(get_rule_health_checker)
        assert all(o is objs[0] for o in objs)


class TestSmartRotationDCLP:
    """smart_rotation.py has 4 separate singletons."""

    LOCKS = ["_rotation_lock", "_time_lock", "_explore_lock", "_comp_cache_lock"]

    def test_has_locks(self):
        import core.brain.smart_rotation as mod
        for lock_name in self.LOCKS:
            assert hasattr(mod, lock_name), f"Missing {lock_name}"

    def test_product_rotation_singleton(self):
        from core.brain.smart_rotation import get_product_rotation
        objs = _race_getter(get_product_rotation)
        assert all(o is objs[0] for o in objs)

    def test_time_awareness_singleton(self):
        from core.brain.smart_rotation import get_time_awareness
        objs = _race_getter(get_time_awareness)
        assert all(o is objs[0] for o in objs)

    def test_exploration_boost_singleton(self):
        from core.brain.smart_rotation import get_exploration_boost
        objs = _race_getter(get_exploration_boost)
        assert all(o is objs[0] for o in objs)

    def test_competitor_cache_singleton(self):
        from core.brain.smart_rotation import get_competitor_cache
        objs = _race_getter(get_competitor_cache)
        assert all(o is objs[0] for o in objs)


class TestStrategyExpanderDCLP:
    def test_has_lock(self):
        import core.brain.strategy_expander as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.brain.strategy_expander import get_strategy_expander
        objs = _race_getter(get_strategy_expander)
        assert all(o is objs[0] for o in objs)


class TestReasoningChainDCLP:
    def test_has_lock(self):
        import core.brain.reasoning_chain as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.brain.reasoning_chain import get_chain_of_thought
        objs = _race_getter(get_chain_of_thought)
        assert all(o is objs[0] for o in objs)


class TestTimeseriesDCLP:
    def test_has_lock(self):
        import core.data.timeseries as mod
        assert hasattr(mod, "_instance_lock")

    def test_thread_safe_singleton(self):
        from core.data.timeseries import get_timeseries
        objs = _race_getter(get_timeseries)
        assert all(o is objs[0] for o in objs)
