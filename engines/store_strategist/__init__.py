"""Store Strategist Engine — W963-28.

Per-store AGI brain. Reads ALL observation signals (funnel,
trajectory, earnings-by-engine, checkup, autonomy-status) +
world_model snapshot, applies deterministic reasoning rules,
outputs a ranked list of recommended actions with confidence
scores + drill commands.

NOT autonomous: recommends, does not execute. The autopilot
bridge (W963-23) and confidence_auto_approver (W963-29) are
the writers that consume these recommendations.

Bible scoring:
  - Q1 (20-store leverage): each store gets its own strategist
    output; operator skims N strategist outputs instead of
    diving into each store's metrics manually.
  - Q2 (substrate composability): pure synthesis — composes
    every observation engine into a single recommendation
    list.
  - Q3 (AI self-learning): the recommendation rules + the
    confidence scoring are the substrate the future AI brain
    layers ON TOP of (deterministic baseline → LLM refines).

CLI:
  shopai strategist                   -- recommend for default store
  shopai strategist --store STORE     -- per-store
  shopai strategist --json            -- machine-readable
  shopai strategist --top N           -- limit to top N
"""
from .flow import StoreStrategistEngine

__all__ = ["StoreStrategistEngine"]
