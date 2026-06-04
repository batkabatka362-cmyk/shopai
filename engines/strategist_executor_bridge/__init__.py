"""Strategist Executor Bridge — W963-37.

Bridges store_strategist (W963-28) recommendations into the
autopilot loop via plan_executor (W963-36). When a store's top
recommendation has high impact + high confidence + matches a
plan template, the bridge auto-composes the matching plan and
queues it.

Loop:
  1. Per store: run store_strategist → get top recommendation
  2. Map recommendation source_signal to plan template:
       cold_start (no products + no rev)    → "cold_start"
       funnel checkouts_completed weak       → "increase_conversion"
       funnel checkouts_started weak         → "increase_conversion"
       trajectory declining                  → "diagnose"
       earnings_quiet + ESP wired            → "increase_traffic"
       trajectory rising + ads wired         → "increase_traffic"
       no recommendation needed              → skip
  3. If confidence × impact >= threshold AND template exists:
     compose plan + enqueue via plan_executor
  4. Record per-store bridge result

Bible scoring:
  Q1 (20-store leverage): replaces operator's "pick top
     recommendation per store + decide which plan to run"
     loop. Bridge runs across the fleet autonomously.
  Q2 (substrate composability): pure synthesis -- composes
     store_strategist + plan_composer + plan_executor +
     active_store. Zero new substrate.
  Q3 (AI self-learning): the recommendation → plan mapping
     is the deterministic baseline. Future LLM brain layers
     on top: same shape, smarter selection.

Safety
------
Quadruple-gated:
  - default dry-run
  - --yes required
  - SHOPAI_STRATEGIST_EXECUTOR_BRIDGE=1 env required
  - SHOPAI_PLAN_EXECUTOR_ENABLED=1 (inherited from
    plan_executor, so live enqueue requires this too)
  - --confidence-floor (default 0.6)

CLI:
  shopai strategist-bridge                  -- dry-run preview
  shopai strategist-bridge --yes            -- live
  shopai strategist-bridge --store STORE    -- per-store
  shopai strategist-bridge --confidence-floor 0.8
  shopai strategist-bridge --json
"""
from .flow import StrategistExecutorBridgeEngine

__all__ = ["StrategistExecutorBridgeEngine"]
