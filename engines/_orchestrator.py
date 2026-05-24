"""Tier 1 Empire Orchestrator -- fleet-level decisioner.

Single-step delegation: Orchestrator knows ONLY Store
Supervisors (Tier 2a), doesn't reach into Cluster Captains.

For each store in the fleet, decides:
  • cycle priority (what does this store NEED most?)
  • cluster-override pin (only these clusters fire)
  • signal hints (drawn from world-model)

Then calls make_supervisor_plan per store + aggregates.

## Tier 1 priority rules (deterministic v1)

Per-store priority computed from world-model snapshot:

  LAUNCHING  -> products < 5 OR orders == 0
                priority: setup, content, acquisition
                opt-in clusters get explicit activation

  GROWING    -> orders > 0 AND repeat_rate < 30%
                priority: acquisition, merchandising, quality

  MATURE     -> orders > 50 AND repeat_rate >= 30%
                priority: retention, pricing, merchandising

  AT_RISK    -> orders > 0 AND no_orders_in_7d
                priority: retention, discovery (find reasons)

  STAGNANT   -> revenue_trend < -10%
                priority: pricing, discovery, acquisition

Each priority maps to a small set of clusters that this
cycle should activate. The remaining clusters are SKIPPED
to focus the captain attention + reduce blast radius.

## Future plug-ins (substrate-first)

- AIOrchestratorStrategy: LLM reads world-model + memory,
  emits per-store priorities
- HistoricalRollupStrategy: looks at last N cycles' outcomes,
  rotates priorities based on which haven't improved
- OperatorOverrideStrategy: respects explicit operator
  "this store: do X" pins

All plug in via the OrchestratorStrategy protocol below.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from engines._store_supervisor import (
    SupervisorPlan,
    make_supervisor_plan,
)


@dataclass
class StorePriority:
    """One store's priority + cluster-override for a cycle."""
    store_id: str
    priority: str  # "launching" / "growing" / "mature" / "at_risk" / "stagnant" / "default"
    cluster_focus: list[str]
    rationale: str
    signals: dict[str, Any] = field(default_factory=dict)


@dataclass
class FleetPlan:
    """Aggregate plan across the fleet."""
    cycle_label: str
    priorities: list[StorePriority] = field(default_factory=list)
    supervisor_plans: list[SupervisorPlan] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_stores(self) -> int:
        return len(self.priorities)

    @property
    def total_to_fire(self) -> int:
        return sum(sp.total_to_fire for sp in self.supervisor_plans)

    @property
    def total_modifications(self) -> int:
        return sum(
            sp.total_modifications for sp in self.supervisor_plans
        )


class OrchestratorStrategy(Protocol):
    """Pluggable: how to decide each store's priority."""

    def decide_priority(
        self, store_id: str, world_model: dict[str, Any],
    ) -> StorePriority:
        ...


# ── Default priority rules (deterministic v1) ──────────────────

_PRIORITY_CLUSTERS = {
    "launching": ["setup", "acquisition", "content"],
    "growing": ["acquisition", "merchandising", "quality"],
    "mature": ["retention", "pricing", "merchandising"],
    "at_risk": ["retention", "discovery"],
    "stagnant": ["pricing", "discovery", "acquisition"],
    "default": [
        # All-cluster default (same as supervisor default
        # activation -- all except opt-in)
        "retention", "pricing", "acquisition", "quality",
        "merchandising", "fulfillment", "governance",
        "discovery",
    ],
}


class DeterministicOrchestratorStrategy:
    """Default v1: deterministic rules over store stats.

    Reads world-model 'stats' section + signals to bucket
    each store into a priority class, then maps to cluster
    focus list.
    """

    def decide_priority(
        self,
        store_id: str,
        world_model: dict[str, Any],
    ) -> StorePriority:
        stats = (world_model or {}).get("stats", {}) or {}
        products = int(stats.get("products", 0) or 0)
        orders = int(stats.get("orders", 0) or 0)
        revenue = float(stats.get("total_revenue", 0.0) or 0.0)

        # LAUNCHING: store doesn't have products yet or
        # zero orders
        if products < 5 or orders == 0:
            return StorePriority(
                store_id=store_id,
                priority="launching",
                cluster_focus=_PRIORITY_CLUSTERS["launching"],
                rationale=(
                    f"products={products} orders={orders} "
                    f"-- still in launch phase"
                ),
                signals={
                    "is_new_store": True,
                    "product_count": products,
                },
            )

        # AT_RISK: store has orders but none recently
        # (we'd want last_order_at from sync section, but
        # world-model doesn't always carry that -- skip for
        # now). Heuristic: low revenue per order ratio.
        avg_order = revenue / orders if orders > 0 else 0.0
        if orders > 5 and avg_order < 10.0:
            return StorePriority(
                store_id=store_id,
                priority="at_risk",
                cluster_focus=_PRIORITY_CLUSTERS["at_risk"],
                rationale=(
                    f"avg_order=${avg_order:.2f} -- "
                    f"suspiciously low; possible churn"
                ),
                signals={"avg_order_value": avg_order},
            )

        # MATURE: meaningful order count
        if orders > 50:
            return StorePriority(
                store_id=store_id,
                priority="mature",
                cluster_focus=_PRIORITY_CLUSTERS["mature"],
                rationale=(
                    f"orders={orders} revenue=${revenue:.2f} "
                    f"-- established store"
                ),
                signals={
                    "is_mature": True,
                    "avg_order_value": avg_order,
                },
            )

        # GROWING: between launch + mature
        return StorePriority(
            store_id=store_id,
            priority="growing",
            cluster_focus=_PRIORITY_CLUSTERS["growing"],
            rationale=(
                f"orders={orders} -- growth phase"
            ),
            signals={"growth_phase": True},
        )


def make_fleet_plan(
    *,
    world_models: dict[str, dict[str, Any]] | None = None,
    strategy: OrchestratorStrategy | None = None,
    cycle_label: str = "default",
) -> FleetPlan:
    """Build a FleetPlan: one StorePriority + SupervisorPlan
    per store.

    Args:
        world_models: Per-store world-model snapshots keyed
            by store_id. If None, an empty fleet is returned
            (operator must supply via CLI or call
            WorldModel().snapshot per store).
        strategy: Decision strategy. Defaults to
            DeterministicOrchestratorStrategy.
        cycle_label: Identifier for this cycle (timestamp,
            run-id, etc). Used in logs + memory.

    Returns:
        Populated :class:`FleetPlan`.
    """
    world_models = world_models or {}
    strategy = strategy or DeterministicOrchestratorStrategy()
    plan = FleetPlan(cycle_label=cycle_label)

    if not world_models:
        plan.notes.append(
            "empty fleet -- no world-models supplied"
        )
        return plan

    # Pull queue stats ONCE for the fleet (shared across all
    # stores). The signal collector reuses these per store.
    queue_stats: dict[str, dict[str, int]] = {}
    try:
        from core.approval.queue import get_approval_queue
        queue_stats = (
            get_approval_queue().stats_by_engine() or {}
        )
    except Exception:  # noqa: BLE001
        queue_stats = {}

    # Signal collector for per-cluster signal auto-derivation
    from engines._captain_signals import HeuristicSignalCollector
    collector = HeuristicSignalCollector()

    for store_id, wm in sorted(world_models.items()):
        priority = strategy.decide_priority(store_id, wm or {})
        plan.priorities.append(priority)

        # Auto-derive per-cluster signals from world-model +
        # queue stats. This is the autonomous-mode keystone --
        # captain reads its environment without operator JSON.
        collected = collector.collect(
            store_id, wm or {}, queue_stats,
        )

        # Layer Tier-1 priority hints on top of collected
        # signals -- priority class fills in gaps when
        # heuristic returns empty for a cluster.
        priority_hints = _signals_for_priority(
            priority.priority, wm or {},
        )
        signals_by_cluster: dict[str, dict[str, Any]] = {}
        for k in set(collected) | set(priority_hints):
            merged = dict(collected.get(k, {}))
            merged.update(priority_hints.get(k, {}))
            signals_by_cluster[k] = merged

        supervisor_plan = make_supervisor_plan(
            store_id=store_id,
            signals_by_cluster=signals_by_cluster,
            cluster_override=priority.cluster_focus,
        )
        plan.supervisor_plans.append(supervisor_plan)

    return plan


def _signals_for_priority(
    priority: str,
    world_model: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Translate priority class into per-cluster signals.

    The signals here are FRAMING signals from the Orchestrator,
    not domain-aggregated data (those come from the signal-
    collector layer, next module). These hint the captain
    which rule branch to activate.
    """
    out: dict[str, dict[str, Any]] = {}
    stats = world_model.get("stats", {}) or {}

    if priority == "launching":
        out["setup"] = {"first_launch": True}
        out["acquisition"] = {"new_signups_count": 1}
        return out

    if priority == "at_risk":
        # Hint retention captain that at-risk customers exist
        out["retention"] = {"at_risk_count": 1}
        out["discovery"] = {"investigate": True}
        return out

    if priority == "mature":
        # Hint retention + pricing to surface their default
        # always-on rules
        out["retention"] = {}  # default rule fires
        out["pricing"] = {}
        out["merchandising"] = {}
        return out

    if priority == "growing":
        out["acquisition"] = {"new_signups_count": 1}
        out["merchandising"] = {}
        out["quality"] = {}
        return out

    if priority == "stagnant":
        out["pricing"] = {"thin_margin_count": 1}
        out["discovery"] = {"investigate": True}
        out["acquisition"] = {"new_signups_count": 1}
        return out

    return out


def fleet_summary(plan: FleetPlan) -> dict[str, Any]:
    """Compact rollup of a FleetPlan -- one row per store."""
    rows: list[dict[str, Any]] = []
    for prio, sp in zip(plan.priorities, plan.supervisor_plans):
        rows.append({
            "store_id": prio.store_id,
            "priority": prio.priority,
            "rationale": prio.rationale,
            "active_clusters": len(sp.active_clusters),
            "fire": sp.total_to_fire,
            "queued": sp.total_modifications,
        })
    return {
        "cycle_label": plan.cycle_label,
        "total_stores": plan.total_stores,
        "total_to_fire": plan.total_to_fire,
        "total_modifications": plan.total_modifications,
        "stores": rows,
    }
