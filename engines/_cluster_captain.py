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

    Use this when caller hasn't supplied signals + just wants
    "run everything safe" behavior. The SignalDrivenStrategy
    below is the smarter default once captains have signal
    inputs from world-model + Pattern Z.
    """

    def select_members(
        self,
        cluster: Cluster,
        wired_members: list[str],
        signals: dict[str, Any],
    ) -> list[str]:
        return list(wired_members)


# ── Signal-driven strategy ────────────────────────────────────
#
# Per-cluster rules: signal threshold -> which engines fire.
# This is the FIRST tier of "captain that thinks". Each rule:
#   key = signal name (read from signals dict)
#   value = (comparison_op, threshold, members_to_fire)
#
# When a signal matches, those member engines are SELECTED for
# this cycle. Engines not matched by any rule are skipped.
# Empty signals dict -> falls back to DeterministicCaptainStrategy
# behavior (fire all wired) so existing callers don't break.

_CLUSTER_RULES: dict[str, list[dict[str, Any]]] = {
    "retention": [
        # at_risk_customer_count > 0 -> fire churn-focused members
        {
            "when": "at_risk_count",
            "op": ">",
            "threshold": 0,
            "fire": [
                "churn_prediction",
                "cohort_analysis",
                "customer_journey",
                "nps_engine",
                "subscription",
            ],
        },
        # abandoned_cart_count > 0 -> fire recovery
        {
            "when": "abandoned_cart_count",
            "op": ">",
            "threshold": 0,
            "fire": ["cart_recovery", "browse_recovery"],
        },
        # default: always-on members regardless of signal
        {
            "when": "*",
            "op": "default",
            "threshold": None,
            "fire": ["loyalty", "customer_effort_score"],
        },
    ],
    "pricing": [
        # thin_margin_count > 0 -> dropshipping + profitability
        {
            "when": "thin_margin_count",
            "op": ">",
            "threshold": 0,
            "fire": ["dropshipping", "profitability_calculator"],
        },
        # default: elasticity always runs (read-only signals)
        {
            "when": "*",
            "op": "default",
            "threshold": None,
            "fire": ["price_elasticity"],
        },
        # discount_opportunity_count > 0 -> discount_strategy
        {
            "when": "discount_opportunity_count",
            "op": ">",
            "threshold": 0,
            "fire": ["discount_strategy"],
        },
    ],
    "quality": [
        # defect_count > 0 -> order_quality
        {
            "when": "defect_count",
            "op": ">",
            "threshold": 0,
            "fire": ["order_quality"],
        },
        # warranty_claim_count > 0 -> warranty
        {
            "when": "warranty_claim_count",
            "op": ">",
            "threshold": 0,
            "fire": ["warranty"],
        },
        # fraud_count > 0 -> fraud_detection
        {
            "when": "fraud_count",
            "op": ">",
            "threshold": 0,
            "fire": ["fraud_detection"],
        },
        # negative_review_count >= 3 -> review_management
        {
            "when": "negative_review_count",
            "op": ">=",
            "threshold": 3,
            "fire": ["review_management"],
        },
    ],
    "fulfillment": [
        # stockout_imminent_count > 0 -> stock_prediction + inventory
        {
            "when": "stockout_imminent_count",
            "op": ">",
            "threshold": 0,
            "fire": ["stock_prediction", "inventory"],
        },
        # pending_returns_count > 0 -> returns_management
        {
            "when": "pending_returns_count",
            "op": ">",
            "threshold": 0,
            "fire": ["returns_management"],
        },
    ],
    "merchandising": [
        # always-on: ranking + scoring (low-cost, always useful)
        {
            "when": "*",
            "op": "default",
            "threshold": None,
            "fire": [
                "product_ranking", "product_scoring",
                "behavioral_data",
            ],
        },
        # declining_product_count > 0 -> product_lifecycle
        {
            "when": "declining_product_count",
            "op": ">",
            "threshold": 0,
            "fire": ["product_lifecycle"],
        },
    ],
    "acquisition": [
        # always-on: targeting + segmentation
        {
            "when": "*",
            "op": "default",
            "threshold": None,
            "fire": ["audience_targeting", "customer_segmentation"],
        },
        # new_signups_count > 0 -> email_marketing
        {
            "when": "new_signups_count",
            "op": ">",
            "threshold": 0,
            "fire": ["email_marketing"],
        },
    ],
}


def _compare(value: Any, op: str, threshold: Any) -> bool:
    if op == "default":
        return True
    try:
        v = float(value)
        t = float(threshold)
    except (TypeError, ValueError):
        return False
    if op == ">":
        return v > t
    if op == ">=":
        return v >= t
    if op == "<":
        return v < t
    if op == "<=":
        return v <= t
    if op == "==":
        return v == t
    return False


class SignalDrivenCaptainStrategy:
    """Per-cluster signal -> member selection.

    Each cluster has a set of rules (see _CLUSTER_RULES). A
    rule fires when its signal threshold is met -- members
    listed in that rule's ``fire`` list are selected.

    Default rules (``when="*"``, ``op="default"``) always
    apply, so always-on members fire regardless of signals.

    Fallback: if no rules exist for a cluster, the strategy
    falls back to DeterministicCaptainStrategy (fire all
    wired). This keeps it safe for clusters without curated
    rules yet (content, governance, discovery, setup).
    """

    def select_members(
        self,
        cluster: Cluster,
        wired_members: list[str],
        signals: dict[str, Any],
    ) -> list[str]:
        rules = _CLUSTER_RULES.get(cluster.name)
        if rules is None:
            # No rules curated yet -> fall back to fire-all
            return list(wired_members)
        selected: set[str] = set()
        for rule in rules:
            if _compare(
                signals.get(rule["when"]),
                rule["op"],
                rule["threshold"],
            ):
                for engine in rule["fire"]:
                    if engine in wired_members:
                        selected.add(engine)
        return sorted(selected)


class MemoryAwareCaptainStrategy:
    """Signal-driven + memory-aware.

    Combines SignalDrivenCaptainStrategy with cluster-memory
    health verdict:
      - healthy   -> use signal-driven selection as-is
      - warning   -> drop members with bad individual history
                     (failed > executed across recent actions)
      - unhealthy -> only "always-on" default-rule members fire
      - unknown   -> signal-driven (no history yet)

    This is the AGI principle: AI uses memory to make better
    decisions. Captain reads cluster health, adjusts member
    selection.
    """

    def __init__(self) -> None:
        self._inner = SignalDrivenCaptainStrategy()

    def select_members(
        self,
        cluster: Cluster,
        wired_members: list[str],
        signals: dict[str, Any],
    ) -> list[str]:
        base = self._inner.select_members(
            cluster, wired_members, signals,
        )
        try:
            from engines._cluster_memory import (
                cluster_health_rollup,
            )
            health = cluster_health_rollup(cluster.name)
        except Exception:  # noqa: BLE001
            health = None

        if health is None:
            return base

        verdict = health.health_verdict
        if verdict in ("healthy", "unknown"):
            return base

        if verdict == "warning":
            # Drop members with bad individual history
            failing: set[str] = set()
            for row in health.member_health:
                actions = (
                    row["executed"] + row["failed"]
                    + row["rejected"]
                )
                if actions > 5 and row["failed"] > row["executed"]:
                    failing.add(row["engine"])
            return [e for e in base if e not in failing]

        # unhealthy: collapse to "always-on" default members
        rules = _CLUSTER_RULES.get(cluster.name, [])
        defaults: set[str] = set()
        for r in rules:
            if r.get("op") == "default":
                for engine in r["fire"]:
                    if engine in wired_members:
                        defaults.add(engine)
        return sorted(defaults & set(base))


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
