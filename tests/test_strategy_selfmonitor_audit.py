"""Tests for audit-pass-51 fixes — defensive hardening across
``core/strategy/*`` and ``core/self_monitor/*``.

Real bugs fixed:

  * StrategyPlanner._plans dict had no lock; concurrent
    create_plan / complete_task / set_active_store calls
    raced.

  * StrategyPlanner.recommend_plan_type(None) crashed on the
    first ``situation.get("financial", {})`` call — now
    coerces None / non-dict to empty dict.

  * StrategyPlanner.recommend_plan_type did
    ``customers.get("churn_risk_pct", 0) > 30`` — if
    churn_risk_pct was present-but-None or a string
    (``"50%"``), Python 3 raised TypeError on the numeric
    comparison. Now coerced via safe_float.

  * StrategyPlanner.check_progress / complete_task /
    get_today_tasks accepted arbitrary plan_id values without
    isinstance-checking — a non-string id crashed the dict
    lookup.

  * GrowthPlanner.create_roadmap / backtrack_requirements
    did ``current_revenue <= 0`` and
    ``target_revenue / current_revenue`` on raw inputs.
    None / non-numeric / negative inputs crashed before
    reaching the error-return path. Also months=0 crashed
    the exponent math.

  * GrowthPlanner._recommend_levers sorted by
    ``{"low": 0, ...}[r["effort"]]`` — an unknown effort
    value crashed the sort with KeyError. Now uses .get
    with a high default.

  * AnomalyDetector._baselines had no lock; concurrent
    update/check raced. Also crashed on non-numeric values
    in the input list and on None metric values in check().

  * AnomalyDetector.get_baselines returned a shallow dict
    copy; caller mutating inner dicts corrupted stored
    state.

  * AutoRecovery._actions_log had no lock; concurrent
    attempt_recovery calls could lose entries.

  * AutoRecovery._recover_high_error_rate did
    ``f"{error_rate:.0%}"`` which raised on None /
    non-numeric error_rate. Now safe_float.

  * CapabilityAssessor.assess did
    ``claimed_confidence - actual_rate`` and
    ``sample_size >= 5`` on raw memory-stat values. Non-
    numeric stats crashed the arithmetic. Now coerced via
    safe_int / safe_float.

  * CapabilityAssessor._get_capability_profile crashed if
    ``self._memory.get_lessons`` raised or returned non-list
    — now try/except + isinstance.

  * SelfDiagnostics.shopify_health_check did
    ``store_config.get(section, {}).get(check_name, False)``
    which crashed when the nested section key was
    present-but-None. Now guarded.

  * SelfDiagnostics.full_scan did numeric comparisons on
    ``metrics.get("conversion_rate", 100) < 1`` which
    crashed on None / non-numeric metric values. Now uses
    safe_float.

  * SystemMonitor._snapshots had no lock; concurrent
    full_check / get_dashboard / get_history races.

  * SystemMonitor.full_check did
    ``health["checks"]["modules"]["healthy"]`` with direct
    dict subscripts — any missing key crashed. Now uses the
    ``(x or {})`` pattern.
"""
from __future__ import annotations

import threading

import pytest

from core.self_monitor.anomaly_detector import AnomalyDetector
from core.self_monitor.auto_recovery import AutoRecovery
from core.self_monitor.capability_assessor import CapabilityAssessor
from core.self_monitor.self_diagnostics import SelfDiagnostics
from core.self_monitor.system_monitor import SystemMonitor
from core.strategy.growth_planner import GrowthPlanner
from core.strategy.strategy_planner import StrategyPlanner


# ═══════════════════════════════════════════════════════════
# StrategyPlanner
# ═══════════════════════════════════════════════════════════


class TestStrategyPlannerDefensive:
    def test_create_plan_unknown_type(self):
        sp = StrategyPlanner()
        r = sp.create_plan("nonexistent")
        assert r["status"] == "error"

    def test_create_plan_non_string_type(self):
        sp = StrategyPlanner()
        r = sp.create_plan(None)  # type: ignore[arg-type]
        assert r["status"] == "error"

    def test_create_plan_non_dict_context(self):
        sp = StrategyPlanner()
        r = sp.create_plan("growth_sprint", context="not a dict")  # type: ignore[arg-type]
        assert r["context"] == {}

    def test_check_progress_non_string_id(self):
        sp = StrategyPlanner()
        r = sp.check_progress(None)  # type: ignore[arg-type]
        assert r["status"] == "not_found"

    def test_complete_task_non_string_id(self):
        sp = StrategyPlanner()
        assert sp.complete_task(None, "x", "y") is False  # type: ignore[arg-type]

    def test_get_today_tasks_non_string_id(self):
        sp = StrategyPlanner()
        assert sp.get_today_tasks(None) == []  # type: ignore[arg-type]

    def test_check_progress_non_int_current_day(self):
        sp = StrategyPlanner()
        plan = sp.create_plan("growth_sprint")
        r = sp.check_progress(plan["plan_id"], current_day="bad")  # type: ignore[arg-type]
        assert "progress_pct" in r


class TestRecommendPlanType:
    def test_none_situation(self):
        """Regression: pre-audit ``None.get("financial")`` crashed."""
        sp = StrategyPlanner()
        r = sp.recommend_plan_type(None)  # type: ignore[arg-type]
        assert "plan_type" in r

    def test_non_dict_situation(self):
        sp = StrategyPlanner()
        r = sp.recommend_plan_type("not a dict")  # type: ignore[arg-type]
        assert "plan_type" in r

    def test_none_churn_risk_pct(self):
        """Regression: ``None > 30`` crashed with TypeError."""
        sp = StrategyPlanner()
        r = sp.recommend_plan_type({"customers": {"churn_risk_pct": None}})
        assert "plan_type" in r

    def test_string_churn_risk_pct(self):
        sp = StrategyPlanner()
        r = sp.recommend_plan_type({"customers": {"churn_risk_pct": "50"}})
        # safe_float("50") = 50, above threshold 30 → recovery.
        assert r["plan_type"] == "recovery"

    def test_non_dict_nested(self):
        sp = StrategyPlanner()
        r = sp.recommend_plan_type({
            "financial": "not a dict",
            "inventory": None,
            "customers": 42,
        })
        assert "plan_type" in r


class TestStrategyPlannerThreadSafety:
    def test_concurrent_create_plan(self):
        sp = StrategyPlanner()
        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def fire():
            try:
                barrier.wait()
                sp.create_plan("growth_sprint")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(sp.get_active_plans()) == 8


# ═══════════════════════════════════════════════════════════
# GrowthPlanner
# ═══════════════════════════════════════════════════════════


class TestGrowthPlannerDefensive:
    def test_none_revenue(self):
        gp = GrowthPlanner()
        r = gp.create_roadmap(None, None)  # type: ignore[arg-type]
        assert r["status"] == "error"

    def test_negative_revenue(self):
        gp = GrowthPlanner()
        r = gp.create_roadmap(-100, 200)
        assert r["status"] == "error"

    def test_currency_string_revenue(self):
        gp = GrowthPlanner()
        r = gp.create_roadmap("$10000", "$25000")  # type: ignore[arg-type]
        assert "monthly_growth_rate" in r
        assert "months" in r

    def test_zero_months_coerced(self):
        gp = GrowthPlanner()
        r = gp.create_roadmap(10000, 25000, months=0)
        assert r["months"] == 6  # Default

    def test_negative_months_coerced(self):
        gp = GrowthPlanner()
        r = gp.create_roadmap(10000, 25000, months=-5)
        assert r["months"] == 6

    def test_non_int_months(self):
        gp = GrowthPlanner()
        r = gp.create_roadmap(10000, 25000, months="six")  # type: ignore[arg-type]
        assert r["months"] == 6

    def test_backtrack_none(self):
        gp = GrowthPlanner()
        r = gp.backtrack_requirements(None, None, None)  # type: ignore[arg-type]
        assert r.get("status") == "error"

    def test_backtrack_non_dict_metrics(self):
        gp = GrowthPlanner()
        r = gp.backtrack_requirements(50000, 6, "not a dict")  # type: ignore[arg-type]
        # Falls back to defaults; produces a valid result.
        assert "required_improvements" in r

    def test_recommend_levers_unknown_effort(self, monkeypatch):
        """Regression: pre-audit the sort lambda did a direct
        dict lookup on ``r["effort"]`` which crashed with
        KeyError on unknown effort values."""
        import core.strategy.growth_planner as mod
        original = dict(mod.GROWTH_LEVERS)
        # Inject a lever with an unexpected effort value.
        mod.GROWTH_LEVERS["experimental"] = {
            "tactics": ["x", "y", "z"],
            "typical_lift": (0.2, 0.5),
            "effort": "extreme",  # Not in the rank dict.
            "time_to_impact": "unknown",
        }
        try:
            gp = GrowthPlanner()
            r = gp.create_roadmap(10000, 25000, months=6)
            # Should not crash on the sort.
            assert "recommended_levers" in r
        finally:
            mod.GROWTH_LEVERS.clear()
            mod.GROWTH_LEVERS.update(original)


# ═══════════════════════════════════════════════════════════
# AnomalyDetector
# ═══════════════════════════════════════════════════════════


class TestAnomalyDetectorDefensive:
    def test_update_baseline_none(self):
        ad = AnomalyDetector()
        ad.update_baseline(None, None)  # type: ignore[arg-type]
        ad.update_baseline("cpu", None)  # type: ignore[arg-type]
        assert "cpu" not in ad.get_baselines()

    def test_update_baseline_mixed_list(self):
        """Non-numeric values filtered via safe_float."""
        ad = AnomalyDetector()
        ad.update_baseline("cpu", [1.0, "bad", None, 2.0, 3.0])
        baseline = ad.get_baselines()["cpu"]
        assert baseline["count"] == 5  # safe_float coerces to 0 for garbage

    def test_check_none_value(self):
        """Regression: None value crashed arithmetic."""
        ad = AnomalyDetector()
        ad.update_baseline("cpu", [1.0, 2.0, 3.0])
        result = ad.check("cpu", None)  # type: ignore[arg-type]
        assert "anomaly" in result

    def test_check_non_string_metric(self):
        ad = AnomalyDetector()
        result = ad.check(None, 5.0)  # type: ignore[arg-type]
        assert result["anomaly"] is False

    def test_check_batch_none(self):
        ad = AnomalyDetector()
        assert ad.check_batch(None) == []  # type: ignore[arg-type]

    def test_get_baselines_deep_copy(self):
        """Regression: shallow copy allowed caller mutation."""
        ad = AnomalyDetector()
        ad.update_baseline("cpu", [1, 2, 3])
        b = ad.get_baselines()
        b["cpu"]["mean"] = 999
        assert ad.get_baselines()["cpu"]["mean"] != 999

    def test_concurrent_update(self):
        ad = AnomalyDetector()
        errors: list[Exception] = []
        stop = threading.Event()

        def writer(i: int):
            try:
                while not stop.is_set():
                    ad.update_baseline(f"metric_{i % 3}", [1, 2, 3, 4, 5])
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def reader():
            try:
                while not stop.is_set():
                    ad.get_baselines()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        threads.append(threading.Thread(target=reader))
        for t in threads:
            t.start()
        import time
        time.sleep(0.1)
        stop.set()
        for t in threads:
            t.join(timeout=2)
        assert not errors


# ═══════════════════════════════════════════════════════════
# AutoRecovery
# ═══════════════════════════════════════════════════════════


class TestAutoRecoveryDefensive:
    def test_attempt_recovery_none_type(self):
        ar = AutoRecovery()
        r = ar.attempt_recovery(None)  # type: ignore[arg-type]
        assert r["recovered"] is False

    def test_attempt_recovery_unknown_type(self):
        ar = AutoRecovery()
        r = ar.attempt_recovery("nonexistent")
        assert r["recovered"] is False

    def test_high_error_rate_non_numeric(self):
        """Regression: pre-audit ``f"{error_rate:.0%}"``
        crashed on None / non-numeric error_rate."""
        ar = AutoRecovery()
        r = ar._recover_high_error_rate({"error_rate": None, "engine_name": "test"})
        assert "recommendation" in r

    def test_high_error_rate_string(self):
        ar = AutoRecovery()
        r = ar._recover_high_error_rate({"error_rate": "bad"})
        assert "recommendation" in r

    def test_concurrent_attempt_recovery(self):
        ar = AutoRecovery()
        errors: list[Exception] = []
        barrier = threading.Barrier(8)

        def fire():
            try:
                barrier.wait()
                ar.attempt_recovery("cache_full")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=fire) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        # All 8 attempts should be in the log.
        assert len(ar.get_action_log(limit=100)) == 8


# ═══════════════════════════════════════════════════════════
# CapabilityAssessor
# ═══════════════════════════════════════════════════════════


class TestCapabilityAssessor:
    def test_assess_no_memory(self):
        ca = CapabilityAssessor(episodic_memory=None)
        r = ca.assess("pricing")
        assert r["sample_size"] == 0

    def test_assess_none_claimed(self):
        """Regression: ``None - actual_rate`` crashed."""
        ca = CapabilityAssessor(episodic_memory=None)
        r = ca.assess("pricing", claimed_confidence=None)  # type: ignore[arg-type]
        assert r["claimed_confidence"] == 50

    def test_assess_non_string_decision_type(self):
        ca = CapabilityAssessor(episodic_memory=None)
        r = ca.assess(None)  # type: ignore[arg-type]
        assert "should_escalate" in r

    def test_assess_memory_raises(self):
        """Memory backend raising must not crash assess."""
        class BrokenMemory:
            def get_success_rate(self, dt=None):
                raise RuntimeError("db down")
            def get_lessons(self, dt, limit=5):
                raise RuntimeError("db down")

        ca = CapabilityAssessor(episodic_memory=BrokenMemory())
        r = ca.assess("pricing")
        assert "sample_size" in r

    def test_assess_memory_returns_non_dict(self):
        class WeirdMemory:
            def get_success_rate(self, dt=None):
                return "not a dict"
            def get_lessons(self, dt, limit=5):
                return "not a list"

        ca = CapabilityAssessor(episodic_memory=WeirdMemory())
        r = ca.assess("pricing")
        assert "sample_size" in r


# ═══════════════════════════════════════════════════════════
# SelfDiagnostics
# ═══════════════════════════════════════════════════════════


class TestSelfDiagnostics:
    def test_shopify_health_check_none_config(self):
        sd = SelfDiagnostics()
        r = sd.shopify_health_check(None)
        assert "score" in r

    def test_shopify_health_check_null_section(self):
        """Regression: ``store_config.get(section, {}).get(...)``
        crashed when section was present-but-None."""
        sd = SelfDiagnostics()
        r = sd.shopify_health_check({"checkout": None, "shipping": None})
        assert "score" in r

    def test_full_scan_none_metrics_comparison(self):
        """Regression: ``metrics.get("conversion_rate", 100) < 1``
        crashed on present-but-None values."""
        sd = SelfDiagnostics()
        r = sd.full_scan(metrics={"conversion_rate": None, "cart_abandonment": None})
        assert "issues_detected" in r

    def test_full_scan_non_numeric_metrics(self):
        sd = SelfDiagnostics()
        r = sd.full_scan(metrics={
            "conversion_rate": "bad",
            "cart_abandonment": "worse",
            "page_load": "slow",
        })
        assert "issues_detected" in r

    def test_full_scan_non_dict_metrics(self):
        sd = SelfDiagnostics()
        r = sd.full_scan(metrics="not a dict")  # type: ignore[arg-type]
        assert r["issues_detected"] == 0


# ═══════════════════════════════════════════════════════════
# SystemMonitor
# ═══════════════════════════════════════════════════════════


class TestSystemMonitor:
    def test_full_check_missing_checks_subkey(self, monkeypatch):
        """Regression: pre-audit ``health["checks"]["modules"]
        ["healthy"]`` crashed on any missing sub-key."""
        sm = SystemMonitor()
        # Patch health checker to return malformed data.
        monkeypatch.setattr(
            sm._health,
            "check_all",
            lambda: {"status": "unknown", "checks": None},
        )
        snapshot = sm.full_check()
        assert snapshot["status"] == "unknown"

    def test_full_check_none_health(self, monkeypatch):
        sm = SystemMonitor()
        monkeypatch.setattr(sm._health, "check_all", lambda: None)
        snapshot = sm.full_check()
        assert "status" in snapshot

    def test_get_history_non_int_limit(self, monkeypatch):
        sm = SystemMonitor()
        monkeypatch.setattr(sm._health, "check_all", lambda: {"status": "ok", "checks": {}})
        sm.full_check()
        r = sm.get_history(limit="bad")  # type: ignore[arg-type]
        assert isinstance(r, list)
        assert len(r) == 1

    def test_concurrent_full_check(self, monkeypatch):
        sm = SystemMonitor()
        monkeypatch.setattr(sm._health, "check_all", lambda: {"status": "ok", "checks": {}})
        errors: list[Exception] = []
        barrier = threading.Barrier(4)

        def fire():
            try:
                barrier.wait()
                sm.full_check()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=fire) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(sm.get_history(limit=100)) == 4
