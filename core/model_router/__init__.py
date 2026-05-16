"""Cost-aware model router.

AGI roadmap Phase 2 layer 3. Decides whether a given AI call
should hit a local (cheap, fast, simpler reasoning) model or a
cloud (expensive, slower, deeper reasoning) model. Without this,
empire-scale Opus calls blow the budget; with this, the system
routes 80% of cheap-classification calls locally and only burns
the cloud budget on the calls that genuinely need it.

The router is a PURE policy module:
  - Doesn't execute models (caller's responsibility).
  - Classifies each call by complexity using deterministic
    heuristics (token count, complexity hints, structured-vs-
    prose ratio).
  - Records usage so daily / hourly budget caps are enforceable.
  - Tracks per-tier latency + cost so future routing decisions
    can use measured signal instead of static heuristics.

The contract is stable. Future revisions can swap the
complexity classifier (e.g. for a small local classifier model)
without changing callers.
"""
from __future__ import annotations

from .router import (
    ModelHint,
    ModelRouter,
    ModelTier,
    RoutingDecision,
    classify,
    route,
)

__all__ = [
    "ModelHint",
    "ModelRouter",
    "ModelTier",
    "RoutingDecision",
    "classify",
    "route",
]
