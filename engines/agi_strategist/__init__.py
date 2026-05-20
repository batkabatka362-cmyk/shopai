"""AGI Strategist Engine — public API.

Top-level goal-decomposition layer for ShopAI's autonomous
merchant. Takes a high-level operator goal ("increase revenue
10% this quarter") and produces a structured plan of
substrategies + action steps that downstream engines can
execute.

Owner workflow::

    from engines.agi_strategist import decompose_goal

    plan = decompose_goal(
        goal="Increase revenue 10% this quarter",
        horizon_days=90,
        current_state={"monthly_revenue": 42_000, "aov": 78.0},
        constraints=["no paid ads below 2.5 ROAS"],
    )

    # plan["data"]["substrategies"] -> list of named
    # sub-goals with target metrics + recommended engines.
    # plan["data"]["actions"] -> first-step actions per
    # substrategy.
"""
from .active_goal import (
    clear_active_goal,
    get_active_goal,
    recommended_engines_for_active_plan,
    set_active_goal,
)
from .decomposer import decompose_goal
from .flow import AGIStrategistEngine

__all__ = [
    "AGIStrategistEngine",
    "clear_active_goal",
    "decompose_goal",
    "get_active_goal",
    "recommended_engines_for_active_plan",
    "set_active_goal",
]
