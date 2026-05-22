"""Capability planner -- deterministic substrate query layer
on top of the capability registry.

Why this exists (per the north-star bible)
------------------------------------------
The registry exposes "what capabilities does ShopAI have?"
This module takes the next step: given a GOAL, surface the
ordered substrate slice that can accomplish it.

Today this is a deterministic, substring-matched walker --
no LLM call. The contract is purposely simple so the LLM-
driven planner (future PR) can swap in behind the same call
site. Right now the planner is consumed by:

  1. Claude (me) during a task -- ``shopai plan <goal>``
     surfaces a candidate plan I can verify + execute.
  2. The autonomous loop (future) -- the planner becomes
     the bridge between "operator-supplied goal" and
     "concrete capability invocations".
  3. Operators -- ``shopai plan "make store launchable"``
     prints the recommended command sequence.

Three queries it answers
------------------------

1. **Goal-to-plan**: "I want to do X. Which capabilities
   compose to accomplish it?"
2. **Audit-driven**: "These audit checks are failing. What
   should I run to close them?"
3. **Capability composition**: "I picked this writer. What
   else do I need to chain (generator? verification?)"

What it does NOT do (yet)
-------------------------

- Reason about edge cases or trade-offs between capabilities
  (that's the LLM-driven planner's job).
- Execute the plan (operator / Claude runs the commands).
- Schedule across multiple stores (that's the multi-store
  workflow runner).
- Reason about scope / authorisation (that's the OAuth
  health audit).

These come in subsequent PRs.
"""
from __future__ import annotations

from .plan import Plan, PlanStep
from .planner import Planner, plan_for_goal, plan_for_audit_gaps
from .llm_planner import LLMPlanner, plan_for_goal_with_llm
from .plan_history import (
    PlanEvent,
    capability_degradations,
    capability_leaderboard,
    capability_revenue_impact,
    clear as clear_plan_history,
    correlate_outcome_by_stats,
    goal_breakdown,
    outcome_breakdown,
    record_outcome,
    record_plan_invocation,
    recent_history,
    successful_plans,
)
from . import auto_demote
from . import auto_promote

__all__ = [
    "Plan",
    "PlanStep",
    "Planner",
    "plan_for_goal",
    "plan_for_audit_gaps",
    "LLMPlanner",
    "plan_for_goal_with_llm",
    "PlanEvent",
    "record_plan_invocation",
    "record_outcome",
    "recent_history",
    "outcome_breakdown",
    "goal_breakdown",
    "successful_plans",
    "capability_leaderboard",
    "capability_revenue_impact",
    "capability_degradations",
    "correlate_outcome_by_stats",
    "clear_plan_history",
    "auto_demote",
    "auto_promote",
]
