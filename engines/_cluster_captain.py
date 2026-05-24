"""Cluster Captain -- the deterministic Tier 2b supervisor.

A captain manages ONE cluster of engines (Tier 3 agents). It:

  • knows ONLY its member engines (no cross-cluster reach)
  • reads signals from world-model + Pattern Z outcomes
  • decides which members to FIRE this cycle (and with which
    apply_* flags)
  • routes modification-tier actions to the approval queue
  • emits cluster-health digest UP to Tier 2a supervisor

Iim n single-step delegation amjuulna. Tier 2a (Store
Supervisor) cluster-iig l toidog -- engine-tai direct
yariltsdaggvi. Captain engine-iig l toidog -- adapter-tai
direct yariltsdaggvi.

## Decision sources (captain reads)

1. **World-model** (per-store) -- store stats, sync state,
   recent decisions
2. **Pattern Z outcomes** -- which member engines have been
   successful recently
3. **Risk catalog** -- which apply_* flags this captain may
   auto-set
4. **Cluster definition** -- which engines belong to this
   cluster
5. **Caller intent** -- optional priority hint from Tier 2a
   ("this cycle: focus retention")

## Output

A CaptainPlan dict:

    {
      "cluster": "retention",
      "store_id": "...",
      "members_to_fire": [
        {
          "engine": "loyalty",
          "apply_flag": "apply_rewards",
          "risk": "additive",
          "auto": True,
        },
        {
          "engine": "churn_prediction",
          "apply_flag": "apply_retention_codes",
          "risk": "additive",
          "auto": True,
        },
      ],
      "members_to_skip": [
        {"engine": "subscription", "reason": "no signal this cycle"},
      ],
      "modifications_queued": [
        # any modification-tier actions enqueued for approval
      ],
    }

## What it does NOT do (intentional)

- Does NOT invoke adapters directly (Tier 3 -> 4 only)
- Does NOT call engines outside its cluster
- Does NOT bypass approval queue for modification tier
- Does NOT execute -- only PLANS. Plan goes back up to Tier
  2a which decides whether to execute.

The default captain here is DETERMINISTIC (signal-based
rules). AI-driven captain (LLM-based) can plug in later via
the ``captain_strategy`` argument -- the architecture is
substrate-first so swapping the decisioner doesn't disturb
the substrate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from engines._clusters import Cluster, get_cluster
from engines._writeback_audit import audit_writeback_coverage
from engines._writeback_risk import classify_writers


@dataclass
class CaptainPlan:
    """Plan emitted by a cluster captain for one decision cycle."""
    cluster: str
    store_id: str | None
    members_to_fire: list[dict[str, Any]] = field(default_factory=list)
    members_to_skip: list[dict[str, Any]] = field(default_factory=list)
    modifications_queued: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def fire_count(self) -> int:
        return len(self.members_to_fire)

    @property
    def auto_count(self) -> int:
        return sum(1 for m in self.members_to_fire if m.get("auto"))


class CaptainStrategy(Protocol):
    """Pluggable strategy for member-selection decisions.

    Today: only DeterministicCaptainStrategy implemented.
    Future: AICaptainStrategy that uses memory + LLM to pick.
    """

    def select_members(
        self,
        cluster: Cluster,
        wired_members: list[str],
        signals: dict[str, Any],
    ) -> list[str]:
        """Return list of engine names to fire this cycle."""
        ...


class DeterministicCaptainStrategy:
    """Default strategy: fire every wired member when the
    cluster is activated. Operator-controlled, predictable.

    Future strategies will add signal-based filtering (e.g.
    only fire churn_prediction when at-risk-customer count
    > threshold).
    """

    def select_members(
        self,
        cluster: Cluster,
        wired_members: list[str],
        signals: dict[str, Any],
    ) -> list[str]:
        # MVP: fire all wired members. Captain logic gets
        # smarter in subsequent commits as we add signal-
        # specific rules per cluster.
        return list(wired_members)


def make_captain_plan(
    cluster_name: str,
    *,
    store_id: str | None = None,
    signals: dict[str, Any] | None = None,
    strategy: CaptainStrategy | None = None,
) -> CaptainPlan:
    """Build a CaptainPlan for the given cluster.

    Args:
        cluster_name: Cluster to plan for (e.g. "retention").
        store_id: Optional store scope -- captain plans are
            per-store under Tier 2a.
        signals: Optional input signals dict (e.g. recent
            world-model stats). The strategy uses these to
            decide.
        strategy: Pluggable decision strategy. Defaults to
            DeterministicCaptainStrategy.

    Returns:
        A CaptainPlan dict the supervisor can dispatch.
    """
    cluster = get_cluster(cluster_name)
    if cluster is None:
        return CaptainPlan(
            cluster=cluster_name,
            store_id=store_id,
            notes=[f"unknown cluster: {cluster_name}"],
        )

    signals = signals or {}
    strategy = strategy or DeterministicCaptainStrategy()
    plan = CaptainPlan(cluster=cluster.name, store_id=store_id)

    # Pull writeback wiring + risk classification ONCE per
    # plan -- cheap (single AST scan) + reused below.
    try:
        wb_report = audit_writeback_coverage("engines")
    except Exception:  # noqa: BLE001
        wb_report = None
    try:
        risk_catalog = classify_writers("engines")
    except Exception:  # noqa: BLE001
        risk_catalog = None

    wired_map: dict[str, list[str]] = {}
    if wb_report is not None:
        for s in wb_report.engines:
            if s.status == "wired":
                wired_map[s.name] = list(s.opt_in_flags)

    risk_map: dict[str, str] = {}
    if risk_catalog is not None:
        for w in risk_catalog.writers:
            # Multiple writer files per engine -- the riskiest
            # one wins (so modification beats additive)
            current = risk_map.get(w.engine, "")
            order = ["additive", "modification", "destructive"]
            if (
                current not in order
                or order.index(w.risk) > order.index(current)
            ):
                risk_map[w.engine] = w.risk

    # Wired members of THIS cluster only
    wired_in_cluster = sorted(
        m for m in cluster.members if m in wired_map
    )
    advisory_in_cluster = sorted(
        m for m in cluster.members if m not in wired_map
    )

    if not wired_in_cluster:
        plan.notes.append(
            f"cluster '{cluster.name}' has no wired members "
            f"({len(cluster.members)} total members, all advisory)"
        )
        for engine in advisory_in_cluster:
            plan.members_to_skip.append({
                "engine": engine,
                "reason": "advisory_only",
            })
        return plan

    selected = strategy.select_members(
        cluster, wired_in_cluster, signals,
    )

    for engine in wired_in_cluster:
        risk = risk_map.get(engine, "unknown")
        apply_flags = [
            f for f in wired_map.get(engine, [])
            if f.startswith("apply_")
        ]
        apply_flag = apply_flags[0] if apply_flags else None

        if engine not in selected:
            plan.members_to_skip.append({
                "engine": engine,
                "reason": "strategy_excluded",
            })
            continue

        if apply_flag is None:
            plan.members_to_skip.append({
                "engine": engine,
                "reason": "no_apply_flag",
            })
            continue

        # Risk-tier dispatch:
        #   additive     -> auto-fire (captain decides)
        #   modification -> enqueue to approval (operator decides)
        #   destructive  -> never auto; escalate
        #   unknown      -> conservatively treat as modification
        if risk == "additive":
            plan.members_to_fire.append({
                "engine": engine,
                "apply_flag": apply_flag,
                "risk": risk,
                "auto": True,
            })
        elif risk in ("modification", "unknown"):
            plan.modifications_queued.append({
                "engine": engine,
                "apply_flag": apply_flag,
                "risk": risk,
                "reason": (
                    "modification tier requires approval"
                    if risk == "modification"
                    else "unknown risk -- conservative gate"
                ),
            })
        elif risk == "destructive":
            plan.notes.append(
                f"engine '{engine}' is destructive -- "
                f"escalating to operator (not enqueued)"
            )
            plan.members_to_skip.append({
                "engine": engine,
                "reason": "destructive_requires_operator",
            })
        else:
            plan.members_to_skip.append({
                "engine": engine,
                "reason": f"unknown_risk_classification:{risk}",
            })

    # Advisory engines: skipped (engine produces only
    # recommendations, no Shopify writeback to gate).
    for engine in advisory_in_cluster:
        plan.members_to_skip.append({
            "engine": engine,
            "reason": "advisory_only",
        })

    return plan


def cluster_health(cluster_name: str) -> dict[str, Any]:
    """Static summary of a cluster's current health.

    Sources:
      - cluster definition (members, KPI)
      - writeback audit (which members are wired)
      - risk classification (per-member risk tier)

    Doesn't read live Shopify or Pattern Z outcome history --
    that's the next-iteration version. This is the cheap
    "what does the cluster look like?" snapshot.
    """
    cluster = get_cluster(cluster_name)
    if cluster is None:
        return {"error": f"unknown cluster: {cluster_name}"}

    try:
        wb = audit_writeback_coverage("engines")
        wired = {s.name for s in wb.engines if s.status == "wired"}
        advisory = {s.name for s in wb.engines if s.status == "advisory"}
    except Exception:  # noqa: BLE001
        wired, advisory = set(), set()

    try:
        risk = classify_writers("engines")
        risk_map: dict[str, str] = {}
        order = ["additive", "modification", "destructive"]
        for w in risk.writers:
            current = risk_map.get(w.engine, "")
            if (
                current not in order
                or order.index(w.risk) > order.index(current)
            ):
                risk_map[w.engine] = w.risk
    except Exception:  # noqa: BLE001
        risk_map = {}

    member_rows: list[dict[str, Any]] = []
    risk_buckets: dict[str, int] = {}
    for engine in sorted(cluster.members):
        wb_status = (
            "wired" if engine in wired
            else "advisory" if engine in advisory
            else "unknown"
        )
        eng_risk = risk_map.get(engine, "n/a")
        risk_buckets[eng_risk] = risk_buckets.get(eng_risk, 0) + 1
        member_rows.append({
            "engine": engine,
            "writeback": wb_status,
            "risk": eng_risk,
        })

    wired_count = sum(1 for r in member_rows if r["writeback"] == "wired")

    return {
        "cluster": cluster.name,
        "description": cluster.description,
        "kpi": cluster.kpi,
        "total_members": len(cluster.members),
        "wired_members": wired_count,
        "advisory_members": len(cluster.members) - wired_count,
        "risk_buckets": risk_buckets,
        "members": member_rows,
    }
