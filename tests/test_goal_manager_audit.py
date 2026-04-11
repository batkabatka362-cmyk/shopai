"""Tests for audit-pass-24 fixes in core/goals/goal_manager.py.

  1. _evaluate_goals used `situation.get("financial", {})` — the
     classic dict.get(k, default) antipattern. If the section was
     present with a None value, .get returned None and the next
     chained .get crashed with AttributeError. Same bug pattern
     fixed in priority_engine pass 21.
  2. critical_alerts / churn_pct / aov comparisons crashed with
     `None > 0` TypeError when the underlying metric was stored
     as None.
  3. _switch_history grew unbounded — slow memory leak in
     long-running daemons.
  4. No thread lock around _current_goal / _switch_history.
  5. _is_seasonal_opportunity used time.localtime() so the same
     calendar moment fired at different real-world times in
     different timezones — non-deterministic for distributed
     deployments.
  6. _is_seasonal_opportunity didn't guard `peak_month - 1` against
     wrapping past 1 → 0, so a January peak entry would silently
     mis-match.
"""
import threading
import time

import pytest


def _gm():
    from core.goals.goal_manager import GoalManager
    return GoalManager()


# ── Defensive section access ────────────────────────────────


class TestNoneSectionHandling:
    def test_financial_section_none_no_crash(self):
        """Regression: previously `situation.get("financial",
        {}).get("health_grade", ...)` crashed when financial was
        present with value None."""
        gm = _gm()
        result = gm.select_goal({
            "financial": None,
            "customers": None,
            "health": None,
            "inventory": None,
        })
        # Did not crash; falls back to default goal
        assert result["goal"] == "maximize_profit"

    def test_top_level_situation_none(self):
        gm = _gm()
        result = gm.select_goal(None)
        assert result["goal"] == "maximize_profit"

    def test_top_level_situation_string(self):
        gm = _gm()
        result = gm.select_goal("not a dict")
        assert result["goal"] == "maximize_profit"


# ── Numeric coercion ────────────────────────────────────────


class TestNumericCoercion:
    def test_critical_alerts_none_does_not_crash(self):
        """Regression: `critical_alerts > 0` crashed with
        TypeError when the value was None."""
        gm = _gm()
        result = gm.select_goal({"financial": {"critical_alerts": None}})
        assert "goal" in result

    def test_churn_pct_none_does_not_crash(self):
        gm = _gm()
        result = gm.select_goal({"customers": {"churn_risk_pct": None}})
        assert "goal" in result

    def test_aov_none_does_not_crash(self):
        gm = _gm()
        result = gm.select_goal({"financial": {"aov": None}})
        assert "goal" in result

    def test_string_metrics_does_not_crash(self):
        gm = _gm()
        result = gm.select_goal({
            "financial": {"critical_alerts": "many", "aov": "high"},
            "customers": {"churn_risk_pct": "moderate"},
        })
        assert "goal" in result


# ── Bounded switch history ──────────────────────────────────


class TestSwitchHistoryBounded:
    def test_history_capped(self):
        gm = _gm()
        # Force many switches
        for i in range(500):
            # Alternate between "survive_crisis" (priority 1, urgent —
            # bypasses hysteresis) and "maximize_profit" (default)
            if i % 2 == 0:
                gm.select_goal(
                    {"financial": {"critical_alerts": 5}},
                    cycle_number=i,
                )
            else:
                gm.select_goal({}, cycle_number=i)
        assert len(gm._switch_history) <= gm._MAX_SWITCH_HISTORY

    def test_get_switch_history_returns_copies(self):
        gm = _gm()
        gm.select_goal(
            {"financial": {"critical_alerts": 5}},
            cycle_number=0,
        )
        gm.select_goal({}, cycle_number=1)
        h1 = gm.get_switch_history()
        if h1:
            h1[0]["mutated"] = "yes"
            h2 = gm.get_switch_history()
            assert "mutated" not in h2[0]


# ── Thread safety ───────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_select_goal_no_crash(self):
        gm = _gm()
        errors: list[Exception] = []

        def worker(start):
            try:
                for i in range(50):
                    gm.select_goal(
                        {"financial": {"critical_alerts": 0, "aov": 25}},
                        cycle_number=start + i,
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_get_current_goal_under_lock(self):
        gm = _gm()
        # Just verify it doesn't deadlock with select_goal
        gm.select_goal({"financial": {"critical_alerts": 5}}, cycle_number=0)
        assert gm.get_current_goal() == "survive_crisis"


# ── UTC seasonal + cross-month guard ────────────────────────


class TestSeasonalUTC:
    def test_seasonal_uses_utc(self, monkeypatch):
        """Force UTC time to a Black Friday prep window and verify
        the seasonal opportunity fires regardless of LOCAL tz."""
        from core.goals import goal_manager as gm_mod

        class _FakeTime:
            tm_mon = 11
            tm_mday = 20  # Black Friday is 22-29; prep window starts 14 days before → 8th

        monkeypatch.setattr(gm_mod.time, "gmtime", lambda *a: _FakeTime())
        gm = _gm()
        assert gm._is_seasonal_opportunity() is True

    def test_seasonal_outside_window(self, monkeypatch):
        from core.goals import goal_manager as gm_mod

        class _FakeTime:
            tm_mon = 6
            tm_mday = 15

        monkeypatch.setattr(gm_mod.time, "gmtime", lambda *a: _FakeTime())
        gm = _gm()
        assert gm._is_seasonal_opportunity() is False

    def test_seasonal_january_no_wraparound_crash(self, monkeypatch):
        """Regression: previously `peak_month - 1` for a January
        peak (peak_month=1) produced month=0, which silently
        mis-matched. The guard now skips peaks at month 1."""
        from core.goals import goal_manager as gm_mod
        # Inject a fake January peak to test the guard
        monkeypatch.setattr(gm_mod, "SEASONAL_PEAKS", [(1, 1, 5, 14)])

        class _FakeTime:
            tm_mon = 12
            tm_mday = 25

        monkeypatch.setattr(gm_mod.time, "gmtime", lambda *a: _FakeTime())
        gm = _gm()
        # Should not raise; the cross-month branch is skipped for
        # peak_month=1.
        assert gm._is_seasonal_opportunity() is False


# ── Real goal selection still works ─────────────────────────


class TestRealSelection:
    def test_critical_alerts_triggers_survive_crisis(self):
        gm = _gm()
        result = gm.select_goal({"financial": {"critical_alerts": 3}})
        assert result["goal"] == "survive_crisis"

    def test_high_churn_triggers_grow_customers(self):
        gm = _gm()
        result = gm.select_goal({"customers": {"churn_risk_pct": 60}})
        assert result["goal"] == "grow_customers"

    def test_low_aov_triggers_increase_aov(self):
        gm = _gm()
        # increase_aov is priority 4 — bypasses hysteresis only at
        # priority <= 2, so we have to advance past HYSTERESIS_CYCLES
        # for the switch to take effect from the default goal.
        from core.goals.goal_manager import HYSTERESIS_CYCLES
        result = gm.select_goal(
            {"financial": {"aov": 25}},
            cycle_number=HYSTERESIS_CYCLES + 1,
        )
        assert result["goal"] == "increase_aov"

    def test_normal_state_returns_maximize_profit(self):
        gm = _gm()
        result = gm.select_goal({"financial": {"aov": 100, "critical_alerts": 0}})
        assert result["goal"] == "maximize_profit"
