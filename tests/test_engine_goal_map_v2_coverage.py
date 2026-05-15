"""Locks in the v2 engine→goal mapping expansion + coverage floor.

Before this PR, only 34 of 131 registered engines had a primary
goal binding (26% coverage). The recommender's
``goal_for_engine`` returned ``unmapped`` for the other 97
engines, making them invisible to ``recommend_engines``.

This file:
  1. Asserts every v2-added mapping is present (regression
     test — if a future PR removes one, this fails)
  2. Asserts a coverage floor — at least 65% of engines must
     be mapped. Below this, the recommender is missing too
     much of the catalogue.
  3. Asserts each canonical goal has at least 1 engine (the
     recommender's ``engines_for_goal`` lookup must never
     return empty for a canonical goal — that'd be a broken
     state).
"""
from __future__ import annotations

import pytest


# Mappings added in the v2 expansion. The list is here so a
# future PR removing any one of them is caught at test time,
# not at production-deploy time.
_V2_PROFIT = [
    "accounting", "financial", "profitability_calculator",
    "payment_optimization", "price_elasticity", "tax_engine",
    "demand_estimator", "demand_analysis",
    "product_optimization", "product_ranking", "product_scoring",
    "forecasting", "checkout_optimizer", "monetization",
    "product_description", "product_filter",
    "product_validation", "product_selection",
]

_V2_GROW = [
    "customer_journey", "customer_support", "ltv_cac_dashboard",
    "subscription", "wishlist", "feedback_collection",
    "feedback_processing", "sentiment_analysis", "cohort_analysis",
    "conversion_tracking", "customer_effort_score",
    "audience_targeting", "influencer", "video_marketing",
    "notification", "warranty",
]

_V2_AOV = ["gift_card", "order_management", "product_variant"]

_V2_CRISIS = [
    "cash_flow", "cashflow_simulator", "backup_recovery",
    "security_monitor", "product_risk",
]

_V2_OPPORTUNITY = [
    "trend_discovery", "opportunity_detection",
    "opportunity_scoring", "market_research",
    "international_expansion", "supplier_discovery",
    "ab_testing", "auto_research", "competitor_analysis",
    "competition_analyzer", "competitor_monitor",
    "marketplace", "stock_prediction",
]


class TestV2MappingsPresent:
    """Each v2-added engine maps to the right goal."""

    @pytest.mark.parametrize("engine", _V2_PROFIT)
    def test_profit(self, engine):
        from core.goals.engine_goal_map import goal_for_engine
        assert goal_for_engine(engine) == "maximize_profit"

    @pytest.mark.parametrize("engine", _V2_GROW)
    def test_grow(self, engine):
        from core.goals.engine_goal_map import goal_for_engine
        assert goal_for_engine(engine) == "grow_customers"

    @pytest.mark.parametrize("engine", _V2_AOV)
    def test_aov(self, engine):
        from core.goals.engine_goal_map import goal_for_engine
        assert goal_for_engine(engine) == "increase_aov"

    @pytest.mark.parametrize("engine", _V2_CRISIS)
    def test_crisis(self, engine):
        from core.goals.engine_goal_map import goal_for_engine
        assert goal_for_engine(engine) == "survive_crisis"

    @pytest.mark.parametrize("engine", _V2_OPPORTUNITY)
    def test_opportunity(self, engine):
        from core.goals.engine_goal_map import goal_for_engine
        assert goal_for_engine(engine) == "capture_opportunity"


# ─── coverage floor ──────────────────────────────────────────────


class TestCoverageFloor:

    def test_mapped_count_above_floor(self):
        """At least 65% of registered engines must be mapped.

        Below this, the recommender misses too much of the
        catalogue and the autonomous loop's learning signal is
        starved.
        """
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP
        from engines.registry import list_engines

        registered = set(list_engines())
        mapped = sum(
            1 for e in registered if e in ENGINE_GOAL_MAP
        )
        coverage = mapped / len(registered)

        assert coverage >= 0.65, (
            f"Mapping coverage dropped to {coverage:.1%} "
            f"({mapped}/{len(registered)}). Add new engines to "
            f"core/goals/engine_goal_map.py."
        )

    def test_every_canonical_goal_has_engines(self):
        """Each of the 5 canonical brain-stack goals must have
        at least 1 engine in the map. An empty goal bucket
        breaks the recommender's ``engines_for_goal`` lookup
        for that goal."""
        from core.goals.engine_goal_map import engines_for_goal
        for goal in (
            "maximize_profit",
            "grow_customers",
            "increase_aov",
            "survive_crisis",
            "capture_opportunity",
        ):
            engines = engines_for_goal(goal)
            assert engines, (
                f"Goal {goal!r} has no engines — recommender "
                f"would return empty for it."
            )

    def test_no_typo_in_goal_names(self):
        """Every mapped goal name is one of the 5 canonicals.
        A typo'd goal silently never matches the goal manager."""
        from core.goals.engine_goal_map import ENGINE_GOAL_MAP

        canonical = {
            "maximize_profit", "grow_customers", "increase_aov",
            "survive_crisis", "capture_opportunity",
        }
        for engine, goal in ENGINE_GOAL_MAP.items():
            assert goal in canonical, (
                f"engine {engine!r} maps to non-canonical goal "
                f"{goal!r}. Allowed: {canonical}"
            )
