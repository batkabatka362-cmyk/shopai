"""Warmup Plan Engine — W963-17.

30-day cold-start playbook. Takes the 16 W963 engines + the
broader ShopAI substrate and weaves them into a day-by-day
schedule the operator can run autonomously.

The plan is deterministic + niche-aware. For each day:
  - intent          -- one-sentence goal
  - actions         -- the concrete `shopai X` commands
  - measurement     -- how to verify it landed
  - pivot_signal    -- when to re-plan

Why
---
Operators with a fresh store know what to do on day 1 (launch
products) and what they want by day 30 (profit). The grey zone
between is where stores die — operator gets bored, fires
random engines, no compounding. The warmup plan turns this
into a tight playbook.

CLI:
  shopai warmup-plan                       -- full 30-day plan
  shopai warmup-plan --day N               -- single day drill
  shopai warmup-plan --niche beauty        -- niche-tuned plan
  shopai warmup-plan --json                -- raw envelope
"""
from .flow import WarmupPlanEngine

__all__ = ["WarmupPlanEngine"]
