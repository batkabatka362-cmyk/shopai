"""Tests for the engine recommender (orchestration brain v1).

The recommender joins three inputs to rank engines for the next
run:
  1. Active goal (explicit caller arg / GoalManager.get_current_goal)
  2. Engine → goal map
  3. Per-goal effectiveness EMA from GoalManager

Output is a structured ``RecommendationResult`` carrying the
primary (goal-aligned) recommendations plus optional alternatives
from other goal buckets.

Coverage:
  1. Goal resolution — explicit arg, manager, fallback.
  2. Primary recommendations sorted by priority.
  3. Effectiveness propagation — higher EMA = higher priority.
  4. Alternatives separation — non-primary engines kept out of
     the primary slot.
  5. Limit + whitelist filters.
  6. Empty / missing manager fallbacks.
  7. Serialisation (``to_dict``).
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from core.brain.engine_recommender import (
    EngineRecommendation,
    RecommendationResult,
    recommend_engines,
    _effectiveness_for,
    _resolve_goal,
)
from core.goals.goal_manager import GoalManager


# ─── Goal resolution ───────────────────────────────────────────


class TestResolveGoal:

    def test_explicit_goal_wins(self):
        mgr = MagicMock()
        mgr.get_current_goal.return_value = "maximize_profit"
        assert _resolve_goal("grow_customers", mgr) == "grow_customers"

    def test_manager_used_when_no_explicit(self):
        mgr = MagicMock()
        mgr.get_current_goal.return_value = "survive_crisis"
        assert _resolve_goal(None, mgr) == "survive_crisis"

    def test_fallback_when_manager_unavailable(self):
        # No explicit goal + manager singleton returns None
        with patch(
            "core.brain.engine_recommender._resolve_default_manager",
            return_value=None,
        ):
            assert _resolve_goal(None, None) == "maximize_profit"

    def test_blank_explicit_goal_falls_through_to_manager(self):
        mgr = MagicMock()
        mgr.get_current_goal.return_value = "increase_aov"
        assert _resolve_goal("   ", mgr) == "increase_aov"

    def test_manager_raising_falls_back(self):
        mgr = MagicMock()
        mgr.get_current_goal.side_effect = RuntimeError("boom")
        # With no explicit goal AND a raising manager, falls to default
        with patch(
            "core.brain.engine_recommender._resolve_default_manager",
            return_value=None,
        ):
            assert _resolve_goal(None, mgr) == "maximize_profit"


# ─── _effectiveness_for ────────────────────────────────────────


class TestEffectivenessFor:

    def test_pulls_from_manager(self):
        mgr = GoalManager()
        mgr.record_goal_outcome(
            "grow_customers",
            {"profit_delta": 5, "revenue_delta": 50, "health_delta": 1},
        )
        eff = _effectiveness_for("grow_customers", mgr)
        # EMA bumped above neutral
        assert eff > 0.5

    def test_neutral_when_no_manager(self):
        assert _effectiveness_for("any_goal", None) == 0.5

    def test_neutral_for_unknown_goal(self):
        mgr = GoalManager()
        assert _effectiveness_for("totally_unknown", mgr) == 0.5

    def test_manager_raising_returns_neutral(self):
        mgr = MagicMock()
        mgr.get_effectiveness.side_effect = RuntimeError("boom")
        assert _effectiveness_for("x", mgr) == 0.5


# ─── recommend_engines — primary path ──────────────────────────


class TestRecommendEnginesPrimary:

    def test_returns_engines_for_active_goal(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=20,
        )
        assert result.active_goal == "grow_customers"
        # All primary picks have goal=grow_customers + alignment=1.0
        for r in result.primary:
            assert r.goal == "grow_customers"
            assert r.alignment == 1.0
        # cart_recovery and loyalty should be in the bucket
        engine_names = {r.engine for r in result.primary}
        assert "cart_recovery" in engine_names
        assert "loyalty" in engine_names

    def test_no_picks_for_unknown_goal(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="totally_made_up", manager=mgr, limit=5,
        )
        # No engines map to an unknown goal
        assert result.primary == []
        assert "no engines map to goal" in result.explanation

    def test_limit_caps_primary(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=3,
        )
        assert len(result.primary) == 3

    def test_whitelist_filters_primary(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers",
            manager=mgr,
            limit=10,
            available_engines={"cart_recovery", "loyalty"},
        )
        engine_names = {r.engine for r in result.primary}
        assert engine_names == {"cart_recovery", "loyalty"}

    def test_whitelist_with_no_matches_returns_empty(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers",
            manager=mgr,
            available_engines={"nonexistent"},
        )
        assert result.primary == []


# ─── recommend_engines — effectiveness propagation ─────────────


class TestEffectivenessPropagation:

    def test_higher_effectiveness_raises_priority(self):
        # Two managers: one with no learning, one bumped up
        baseline_mgr = GoalManager()
        bumped_mgr = GoalManager()
        for _ in range(5):
            bumped_mgr.record_goal_outcome(
                "grow_customers",
                {"profit_delta": 5, "revenue_delta": 50,
                 "health_delta": 1},
            )

        baseline = recommend_engines(
            goal="grow_customers", manager=baseline_mgr, limit=1,
        )
        bumped = recommend_engines(
            goal="grow_customers", manager=bumped_mgr, limit=1,
        )

        assert bumped.primary[0].priority > baseline.primary[0].priority
        assert bumped.primary[0].effectiveness > 0.5
        assert baseline.primary[0].effectiveness == 0.5

    def test_priority_formula(self):
        """priority = alignment * (0.5 + 0.5 * effectiveness)"""
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=1,
        )
        r = result.primary[0]
        expected = r.alignment * (0.5 + 0.5 * r.effectiveness)
        assert r.priority == pytest.approx(expected, rel=1e-6)

    def test_neutral_effectiveness_gives_mid_priority(self):
        """0.5 EMA → priority = 1.0 * (0.5 + 0.5 * 0.5) = 0.75"""
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=1,
        )
        assert result.primary[0].priority == pytest.approx(0.75, rel=1e-6)


# ─── recommend_engines — alternatives ──────────────────────────


class TestAlternatives:

    def test_alternatives_carry_other_goals(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=5,
        )
        # All alternatives have alignment 0 (non-primary)
        for r in result.alternatives:
            assert r.alignment == 0.0
            # Their primary goal differs from active
            assert r.goal != "grow_customers"

    def test_alternatives_capped_by_limit(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=3,
        )
        assert len(result.alternatives) <= 3

    def test_include_alternatives_false_returns_empty(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers",
            manager=mgr,
            include_alternatives=False,
        )
        assert result.alternatives == []

    def test_alternatives_sorted_by_effectiveness(self):
        # Bump one alt goal so its engines rank higher
        mgr = GoalManager()
        for _ in range(5):
            mgr.record_goal_outcome(
                "increase_aov",
                {"profit_delta": 5, "revenue_delta": 30,
                 "health_delta": 1},
            )

        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=10,
        )
        # The bumped aov engines should appear before pure-neutral
        # profit engines in the alternatives bucket.
        if len(result.alternatives) >= 2:
            for i in range(len(result.alternatives) - 1):
                assert (
                    result.alternatives[i].effectiveness
                    >= result.alternatives[i + 1].effectiveness
                )


# ─── recommend_engines — goal resolution end-to-end ────────────


class TestGoalResolutionE2E:

    def test_no_goal_uses_manager_current(self):
        mgr = GoalManager()
        # Default current is maximize_profit.
        # Use generous limit so we see all profit engines (v2
        # expanded the map from ~7 to ~30 profit engines).
        result = recommend_engines(manager=mgr, limit=100)
        assert result.active_goal == "maximize_profit"
        engine_names = {r.engine for r in result.primary}
        # discount_strategy & dynamic_pricing are profit engines
        assert "discount_strategy" in engine_names
        assert "dynamic_pricing" in engine_names

    def test_no_goal_and_no_manager_falls_back(self):
        with patch(
            "core.brain.engine_recommender._resolve_default_manager",
            return_value=None,
        ):
            result = recommend_engines(limit=5)
        # Falls back to maximize_profit
        assert result.active_goal == "maximize_profit"


# ─── Serialisation ─────────────────────────────────────────────


class TestSerialization:

    def test_recommendation_to_dict(self):
        r = EngineRecommendation(
            engine="cart_recovery",
            goal="grow_customers",
            alignment=1.0,
            effectiveness=0.65,
            priority=0.825,
            reason="primary engine",
        )
        d = r.to_dict()
        assert d["engine"] == "cart_recovery"
        assert d["goal"] == "grow_customers"
        # All three floats rounded to 3 decimals
        assert isinstance(d["alignment"], float)
        assert isinstance(d["effectiveness"], float)
        assert isinstance(d["priority"], float)
        assert d["reason"] == "primary engine"

    def test_result_to_dict(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=2,
        )
        d = result.to_dict()
        assert d["active_goal"] == "grow_customers"
        assert isinstance(d["primary"], list)
        assert isinstance(d["alternatives"], list)
        assert d["source"] == "rules"
        assert "explanation" in d


# ─── Edge cases ────────────────────────────────────────────────


class TestEdgeCases:

    def test_zero_limit_returns_one_min(self):
        """``max(1, limit)`` floor — even ``limit=0`` returns >=1
        item if available."""
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=0,
        )
        assert len(result.primary) >= 1

    def test_explanation_mentions_top_pick(self):
        mgr = GoalManager()
        result = recommend_engines(
            goal="grow_customers", manager=mgr, limit=5,
        )
        # Explanation mentions the top engine name
        assert result.primary[0].engine in result.explanation

    def test_each_canonical_goal_has_engines(self):
        """Sanity audit — every canonical goal in the GOAL_DEFINITIONS
        set has at least one engine mapped to it. Catches table
        drift if a goal gets renamed without updating the map."""
        mgr = GoalManager()
        canonical = [
            "maximize_profit", "grow_customers", "increase_aov",
            "survive_crisis", "capture_opportunity",
        ]
        for goal in canonical:
            result = recommend_engines(
                goal=goal, manager=mgr, limit=10,
                include_alternatives=False,
            )
            assert result.primary, (
                f"goal {goal!r} has no engines in ENGINE_GOAL_MAP"
            )
