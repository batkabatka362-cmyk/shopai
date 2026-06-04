"""Plan Composer Engine — W963-31.

Goal → multi-step substrate plan. The capstone of the AGI
brain trio (W963-28 strategist + W963-30 browser + W963-31
composer):

  strategist (W963-28): reads store state, ranks needed actions
  browser    (W963-30): finds engines that satisfy each action
  composer   (W963-31): chains them into an ordered plan

Output: a Plan with N steps, each step naming a substrate
engine + drill command + reasoning + estimated impact. The
operator (or future autopilot) approves the whole plan as one
unit instead of N individual PENDINGs.

Bible scoring:
  Q1 (20-store leverage): same plan template can fan out
     across stores via fleet_autopilot.
  Q2 (substrate composability): pure synthesis -- composes
     strategist + browser + capability registry. Zero new
     substrate.
  Q3 (AI self-learning): deterministic baseline plan; the
     future LLM brain can rerank steps based on per-store
     outcome history. Substrate that the AI brain layers
     ON TOP of, not against.

Plan templates (built-in goals):
  - cold_start: catalog seed -> launch -> content -> ads
  - increase_conversion: funnel diagnose -> CRO -> cart_recovery
  - increase_traffic: ads wire -> ads launch -> social pulse
  - retain_customers: welcome series -> review request -> loyalty
  - diagnose: checkup -> strategist -> bigpicture

Custom goal phrases go through capability_browser ranking.

CLI:
  shopai plan-compose "cold_start"                 -- canonical template
  shopai plan-compose "increase conversion"        -- alias
  shopai plan-compose "get traffic" --store STORE  -- custom goal
  shopai plan-compose "X" --max-steps 5            -- cap
  shopai plan-compose "X" --json
"""
from .flow import PlanComposerEngine

__all__ = ["PlanComposerEngine"]
