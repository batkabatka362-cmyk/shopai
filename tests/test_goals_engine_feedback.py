"""Tests for the goals × engine-feedback wiring.

End-to-end coverage of the loop:

  approval.executed/failed (hooks dispatcher)
    → goal_feedback subscriber
    → GoalManager.record_goal_outcome
    → per-goal EMA updated

The wiring depends on PR #88's hooks dispatcher. Tests use the
same ``_disable_test_env_guard`` autouse fixture pattern so the
dispatcher fires under pytest.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core import hooks
from core.goals.engine_goal_map import (
    ENGINE_GOAL_MAP,
    engines_for_goal,
    goal_for_engine,
    is_mapped,
)
from core.goals.goal_feedback import (
    register_goal_feedback,
    reset_for_tests,
    _derive_metrics,
    _record_event,
)
from core.goals.goal_manager import GoalManager


@pytest.fixture(autouse=True)
def _disable_test_env_guard():
    """Turn off the hooks test-bypass so handlers actually fire."""
    with patch(
        "core.hooks.dispatcher._is_test_environment",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_hooks():
    hooks.clear()
    reset_for_tests()
    yield
    hooks.clear()
    reset_for_tests()


@pytest.fixture
def fresh_manager():
    """A fresh GoalManager per test — no state leak between cases."""
    return GoalManager()


# ─── ENGINE_GOAL_MAP ───────────────────────────────────────────


class TestEngineGoalMap:

    def test_profit_engines_mapped_correctly(self):
        assert goal_for_engine("discount_strategy") == "maximize_profit"
        assert goal_for_engine("dynamic_pricing") == "maximize_profit"
        assert goal_for_engine("pricing") == "maximize_profit"

    def test_growth_engines_mapped_correctly(self):
        assert goal_for_engine("cart_recovery") == "grow_customers"
        assert goal_for_engine("loyalty") == "grow_customers"
        assert goal_for_engine("churn_prediction") == "grow_customers"
        assert goal_for_engine("affiliate") == "grow_customers"

    def test_aov_engines_mapped_correctly(self):
        assert goal_for_engine("bundle") == "increase_aov"
        assert goal_for_engine("upsell") == "increase_aov"
        assert goal_for_engine("cross_sell") == "increase_aov"

    def test_crisis_engines_mapped_correctly(self):
        assert goal_for_engine("fraud_detection") == "survive_crisis"
        assert goal_for_engine("returns_management") == "survive_crisis"
        assert goal_for_engine("product_lifecycle") == "survive_crisis"
        assert goal_for_engine("inventory") == "survive_crisis"

    def test_opportunity_engines_mapped_correctly(self):
        assert goal_for_engine("ads_spy") == "capture_opportunity"
        assert goal_for_engine("trend_detection") == "capture_opportunity"
        assert goal_for_engine("campaign_strategy") == "capture_opportunity"

    def test_unknown_engine_returns_unmapped(self):
        assert goal_for_engine("not_an_engine") == "unmapped"
        assert goal_for_engine("") == "unmapped"

    def test_non_string_returns_unmapped(self):
        assert goal_for_engine(None) == "unmapped"
        assert goal_for_engine(42) == "unmapped"

    def test_is_mapped_helper(self):
        assert is_mapped("discount_strategy") is True
        assert is_mapped("not_an_engine") is False

    def test_engines_for_goal_returns_sorted(self):
        growth = engines_for_goal("grow_customers")
        assert growth == sorted(growth)
        assert "cart_recovery" in growth
        assert "loyalty" in growth
        # AOV engines shouldn't appear
        assert "bundle" not in growth

    def test_engines_for_unknown_goal(self):
        assert engines_for_goal("nonexistent") == []

    def test_all_mapped_engines_have_valid_goal(self):
        """Sanity: every entry in ENGINE_GOAL_MAP maps to one of
        the 5 canonical goal names. Catches typos."""
        valid_goals = {
            "maximize_profit", "grow_customers", "increase_aov",
            "survive_crisis", "capture_opportunity",
        }
        for engine, goal in ENGINE_GOAL_MAP.items():
            assert goal in valid_goals, (
                f"engine {engine!r} maps to unknown goal {goal!r}"
            )


# ─── _derive_metrics ───────────────────────────────────────────


class TestDeriveMetrics:

    def test_passes_through_known_keys(self):
        metrics = _derive_metrics(
            {"profit_delta": 10.0, "revenue_delta": 100.0,
             "health_delta": 0.5, "extra": "ignored"},
            succeeded=True,
        )
        assert metrics == {
            "profit_delta": 10.0,
            "revenue_delta": 100.0,
            "health_delta": 0.5,
        }

    def test_empty_result_uses_health_delta_sign(self):
        # Success → positive health delta
        assert _derive_metrics({}, succeeded=True) == {
            "health_delta": 1.0,
        }
        # Failure → negative
        assert _derive_metrics({}, succeeded=False) == {
            "health_delta": -1.0,
        }

    def test_none_result_uses_health_delta(self):
        assert _derive_metrics(None, succeeded=True) == {
            "health_delta": 1.0,
        }

    def test_non_dict_result_uses_health_delta(self):
        assert _derive_metrics("garbage", succeeded=True) == {
            "health_delta": 1.0,
        }

    def test_non_numeric_delta_is_skipped(self):
        # If profit_delta is unparseable, fall through to the
        # health_delta fallback so the EMA still updates.
        metrics = _derive_metrics(
            {"profit_delta": "not a number"},
            succeeded=True,
        )
        # Falls back to health_delta since no numeric delta found.
        assert metrics == {"health_delta": 1.0}

    def test_partial_metrics_supplemented_only_if_none_extracted(self):
        # If at least one numeric delta is extracted, no fallback.
        metrics = _derive_metrics(
            {"revenue_delta": 50.0}, succeeded=False,
        )
        # health_delta NOT added — the revenue_delta carries the
        # sign signal already.
        assert metrics == {"revenue_delta": 50.0}


# ─── _record_event (handler payload routing) ───────────────────


class TestRecordEvent:

    def test_routes_to_engines_primary_goal(self, fresh_manager):
        _record_event(
            {"data": {
                "engine": "cart_recovery",
                "result": {},
            }},
            fresh_manager,
            succeeded=True,
        )
        # cart_recovery → grow_customers
        assert fresh_manager.get_effectiveness("grow_customers") > 0.5
        # maximize_profit untouched
        assert fresh_manager.get_effectiveness("maximize_profit") == 0.5

    def test_unmapped_engine_skipped(self, fresh_manager):
        _record_event(
            {"data": {
                "engine": "unknown_engine",
                "result": {},
            }},
            fresh_manager,
            succeeded=True,
        )
        # No engine mapped → no goal EMA moves
        assert fresh_manager.get_effectiveness_stats() == {}

    def test_missing_engine_skipped(self, fresh_manager):
        _record_event(
            {"data": {"engine": "", "result": {}}},
            fresh_manager,
            succeeded=True,
        )
        assert fresh_manager.get_effectiveness_stats() == {}

    def test_non_dict_event_skipped(self, fresh_manager):
        _record_event("not a dict", fresh_manager, succeeded=True)
        assert fresh_manager.get_effectiveness_stats() == {}

    def test_non_dict_data_skipped(self, fresh_manager):
        _record_event(
            {"data": "garbage"}, fresh_manager, succeeded=True,
        )
        assert fresh_manager.get_effectiveness_stats() == {}

    def test_manager_exception_doesnt_propagate(self, fresh_manager):
        """If the manager's record_goal_outcome raises, the
        feedback handler swallows it (otherwise one bad event
        could halt the hooks fan-out)."""
        with patch.object(
            fresh_manager,
            "record_goal_outcome",
            side_effect=RuntimeError("boom"),
        ):
            # Should NOT raise
            _record_event(
                {"data": {
                    "engine": "cart_recovery",
                    "result": {},
                }},
                fresh_manager,
                succeeded=True,
            )


# ─── register_goal_feedback ─────────────────────────────────────


class TestRegisterGoalFeedback:

    def test_register_returns_true_when_hooks_available(
        self, fresh_manager,
    ):
        result = register_goal_feedback(manager=fresh_manager)
        assert result is True

    def test_register_idempotent(self, fresh_manager):
        register_goal_feedback(manager=fresh_manager)
        # Re-register doesn't double-attach. Snapshot pattern
        # count before / after.
        first_patterns = hooks.registered_patterns()
        register_goal_feedback(manager=fresh_manager)
        second_patterns = hooks.registered_patterns()
        assert first_patterns == second_patterns

    def test_register_attaches_executed_and_failed_handlers(
        self, fresh_manager,
    ):
        register_goal_feedback(manager=fresh_manager)
        patterns = hooks.registered_patterns()
        assert "approval.executed" in patterns
        assert "approval.failed" in patterns


# ─── End-to-end: hooks → feedback → manager EMA ────────────────


class TestEndToEnd:

    def test_executed_event_bumps_goal_ema(self, fresh_manager):
        register_goal_feedback(manager=fresh_manager)

        hooks.emit("approval.executed", {
            "action_id": "appr_1",
            "engine": "cart_recovery",
            "success": True,
            "result": {"profit_delta": 5.0, "revenue_delta": 50.0},
        })

        # cart_recovery → grow_customers
        eff = fresh_manager.get_effectiveness("grow_customers")
        assert eff > 0.5

    def test_failed_event_drops_goal_ema(self, fresh_manager):
        register_goal_feedback(manager=fresh_manager)

        hooks.emit("approval.failed", {
            "action_id": "appr_2",
            "engine": "discount_strategy",
            "success": False,
            "result": {},
        })

        eff = fresh_manager.get_effectiveness("maximize_profit")
        assert eff < 0.5

    def test_multiple_outcomes_for_same_goal_accumulate(
        self, fresh_manager,
    ):
        register_goal_feedback(manager=fresh_manager)

        # Three successful loyalty actions
        for i in range(3):
            hooks.emit("approval.executed", {
                "action_id": f"appr_{i}",
                "engine": "loyalty",
                "success": True,
                "result": {"profit_delta": 2.0},
            })

        stats = fresh_manager.get_effectiveness_stats()
        assert stats["grow_customers"]["n"] == 3
        assert stats["grow_customers"]["effectiveness"] > 0.5

    def test_unmapped_engine_doesnt_affect_ema(self, fresh_manager):
        register_goal_feedback(manager=fresh_manager)

        hooks.emit("approval.executed", {
            "action_id": "appr_x",
            "engine": "completely_made_up",
            "success": True,
            "result": {},
        })

        # No goal effectiveness should move
        assert fresh_manager.get_effectiveness_stats() == {}

    def test_crisis_failure_doesnt_propagate_to_other_goals(
        self, fresh_manager,
    ):
        """A failed inventory action drops survive_crisis but
        leaves maximize_profit untouched. Confirms attribution
        is scoped to the primary goal of the action's engine."""
        register_goal_feedback(manager=fresh_manager)

        hooks.emit("approval.failed", {
            "action_id": "appr_inv",
            "engine": "inventory",
            "success": False,
            "result": {},
        })

        # inventory → survive_crisis dropped
        assert fresh_manager.get_effectiveness("survive_crisis") < 0.5
        # maximize_profit untouched (still at neutral default)
        assert fresh_manager.get_effectiveness("maximize_profit") == 0.5

    def test_hook_emits_post_register_only(self, fresh_manager):
        """Events emitted BEFORE register_goal_feedback shouldn't
        reach the manager — confirms registration is the gating
        action, not just module import."""
        hooks.emit("approval.executed", {
            "action_id": "appr_pre",
            "engine": "cart_recovery",
            "success": True,
            "result": {},
        })

        # No handler registered yet → manager untouched
        assert fresh_manager.get_effectiveness_stats() == {}

        # Now register; subsequent events flow through.
        register_goal_feedback(manager=fresh_manager)
        hooks.emit("approval.executed", {
            "action_id": "appr_post",
            "engine": "cart_recovery",
            "success": True,
            "result": {},
        })
        assert fresh_manager.get_effectiveness_stats() != {}
