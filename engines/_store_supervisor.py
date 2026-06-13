"""Store Supervisor (Tier 2a) -- per-store middle manager.

Sits between Tier 1 Orchestrator (empire-level) and Tier 2b
cluster captains. For one store, one cycle:

  • reads the store's world-model snapshot
  • decides WHICH clusters to activate this cycle (priorities)
  • calls each active cluster's captain with appropriate signals
  • aggregates captain plans into a unified supervisor plan
  • returns the plan UP to Tier 1 (or operator) for review/execution

This is the layer that turns the cluster captains from
"available via CLI" into "called automatically by the
autonomous cycle." Without it, captains exist but never get
invoked in production.

## Architecture position

```
                    ORCHESTRATOR (Tier 1)
                          │
                          │ priorities + budget
                          ▼
                  ┌───────────────────┐
                  │  STORE SUPERVISOR │  ← THIS MODULE
                  │     (Tier 2a)     │
                  └────────┬──────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
  retention captain   pricing captain   quality captain ...
        │                  │                  │
        ▼                  ▼                  ▼
     engines            engines            engines
```

## Single-step delegation respected

Supervisor knows ONLY captains -- doesn't reach into engines.
Captains know ONLY their cluster -- don't reach into adapters.
Engines know ONLY adapter capabilities. Each tier delegates
to the one directly below.

## What supervisor decides

For each cluster, supervisor decides:
  1. ACTIVATE this cycle?  (default: yes for all "always-on"
     clusters; certain clusters are setup-only)
  2. What signals to feed the captain? (drawn from world-model
     + Pattern Z outcomes -- this is "store-specific context")

The captain then decides WHICH MEMBERS to fire based on
signals + risk tier. Supervisor doesn't second-guess the
captain.

## Activation policy

Default: every cluster activates every cycle EXCEPT:
  - "setup" cluster: only on first launch (operator-driven)
  - "content": opt-in (operator handles content personally)

Empire-Orchestrator (Tier 1) can override per-cycle:
  - "this cycle: pricing-priority, skip discovery"

## What supervisor does NOT do

  - Does NOT invoke engines directly
  - Does NOT call adapters
  - Does NOT execute -- only PLANS. Caller (Tier 1 or CLI
    operator) decides whether to invoke.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engines._clusters import list_clusters
from engines._cluster_captain import (
    CaptainPlan,
    SignalDrivenCaptainStrategy,
    make_captain_plan,
)


# Clusters that DON'T fire on every autonomous cycle.
# These are setup-once or opt-in only.
_OPT_IN_CLUSTERS = frozenset({
    "setup",     # first-launch only
    "content",   # operator handles content personally
})


@dataclass
class SupervisorPlan:
    """Aggregate plan: all captain plans for one store-cycle."""
    store_id: str | None
    active_clusters: list[str] = field(default_factory=list)
    skipped_clusters: list[dict[str, Any]] = field(default_factory=list)
    captain_plans: list[CaptainPlan] = field(default_factory=list)

    @property
    def total_to_fire(self) -> int:
        return sum(p.fire_count for p in self.captain_plans)

    @property
    def total_modifications(self) -> int:
        return sum(
            len(p.modifications_queued)
            for p in self.captain_plans
        )

    @property
    def total_skipped(self) -> int:
        return sum(
            len(p.members_to_skip)
            for p in self.captain_plans
        )


def make_supervisor_plan(
    *,
    store_id: str | None = None,
    signals_by_cluster: dict[str, dict[str, Any]] | None = None,
    cluster_override: list[str] | None = None,
    store_stats: dict[str, Any] | None = None,
) -> SupervisorPlan:
    """Build a supervisor plan for one store-cycle.

    Args:
        store_id: Store scope. None = fleet-wide (operator
            ad-hoc).
        signals_by_cluster: Optional per-cluster signals dict
            keyed by cluster name. Each cluster's captain
            uses its slice. Example:
                {"retention": {"at_risk_count": 5},
                 "pricing": {"thin_margin_count": 3}}
        cluster_override: If supplied, only these clusters
            activate (skip the rest). For Tier 1 priority-
            steering -- "this cycle: retention focus."
        store_stats: Optional world_model.stats dict for the
            store. Threaded through to captains so they can
            skip engines whose primary input is empty
            (Wave 42).

    Returns:
        Populated :class:`SupervisorPlan`.
    """
    signals_by_cluster = signals_by_cluster or {}
    plan = SupervisorPlan(store_id=store_id)

    # Decide which clusters to activate this cycle
    all_clusters = list_clusters()
    activation_set: set[str]
    if cluster_override is not None:
        # Tier 1 priority override -- operator-authoritative.
        # Even opt-in clusters activate when explicitly listed
        # (e.g. `cluster fire setup --yes`).
        activation_set = {
            c.name for c in all_clusters
            if c.name in cluster_override
        }
    else:
        # Default: all clusters EXCEPT opt-in-only
        activation_set = {
            c.name for c in all_clusters
            if c.name not in _OPT_IN_CLUSTERS
        }

    for cluster in all_clusters:
        if cluster.name not in activation_set:
            # When override is explicit, the operator chose
            # this cluster off -- record that as the reason.
            # opt_in_only only applies when the supervisor
            # is choosing on its own.
            if cluster_override is not None:
                reason = "not_in_priority_override"
            else:
                reason = "opt_in_only"
            plan.skipped_clusters.append({
                "cluster": cluster.name,
                "reason": reason,
            })
            continue

        # Pull cluster-specific signals (caller supplied OR
        # empty -- captain falls back to fire-all-wired)
        signals = signals_by_cluster.get(cluster.name) or {}

        # Strategy selection:
        #   SHOPAI_AI_STRATEGY=1 -> AICaptainStrategy
        #   signals supplied     -> SignalDrivenCaptainStrategy
        #   else                 -> Deterministic (caller-default)
        import os as _os
        if _os.environ.get("SHOPAI_AI_STRATEGY"):
            try:
                from engines._ai_strategies import (
                    AICaptainStrategy,
                )
                strategy = AICaptainStrategy()
            except Exception:  # noqa: BLE001
                strategy = (
                    SignalDrivenCaptainStrategy() if signals
                    else None
                )
        else:
            strategy = (
                SignalDrivenCaptainStrategy() if signals else None
            )

        captain_plan = make_captain_plan(
            cluster.name,
            store_id=store_id,
            signals=signals,
            strategy=strategy,
            store_stats=store_stats,
        )
        plan.active_clusters.append(cluster.name)
        plan.captain_plans.append(captain_plan)

    return plan


def supervisor_summary(plan: SupervisorPlan) -> dict[str, Any]:
    """Roll up a SupervisorPlan into a single-row summary.

    Used by Tier 1 orchestrator + dashboards. Shows the
    decision shape without diving into per-engine detail.
    """
    cluster_rows: list[dict[str, Any]] = []
    for cp in plan.captain_plans:
        cluster_rows.append({
            "cluster": cp.cluster,
            "fire": cp.fire_count,
            "queued": len(cp.modifications_queued),
            "skipped": len(cp.members_to_skip),
            "notes": cp.notes,
        })
    return {
        "store_id": plan.store_id,
        "active_clusters": len(plan.active_clusters),
        "skipped_clusters": len(plan.skipped_clusters),
        "total_to_fire": plan.total_to_fire,
        "total_modifications": plan.total_modifications,
        "total_skipped": plan.total_skipped,
        "cluster_breakdown": cluster_rows,
    }
