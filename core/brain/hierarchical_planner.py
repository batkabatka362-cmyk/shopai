"""Hierarchical planner — long-horizon goal decomposition.

v3-D7 planner produces a flat DAG of ≤ 8 nodes. Real operator goals
("double revenue in 30 days", "dominate the pet accessories niche",
"diversify to 3 stores by Q4") need multi-level decomposition:

    Goal                                     (vision, 30+ day horizon)
      ├─ Sub-goal 1                          (weekly milestone)
      │    ├─ Task 1.1                       (daily action cluster)
      │    │    ├─ Action 1.1.a              (single pipeline run)
      │    │    └─ Action 1.1.b
      │    └─ Task 1.2
      └─ Sub-goal 2

The decomposer maps each goal to a canonical schema of sub-goals,
then to well-typed tasks, then to flat actions the existing v3
planner can execute. Each level carries:

  • horizon_days     — when the level is expected to complete
  • budget_usd        — cost cap across descendants
  • owner_signoff     — whether humans are in the loop for this level
  • success_criteria  — measurable condition (e.g. "revenue_30d ≥ 20 % up")

No LLM required for the standard intents; free-form goals fall back
to the reasoner + planner stack. The hierarchy persists as
``category=hierarchical_plan`` memory events so the brain can look
at past plans to sharpen future decomposition.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


Horizon = Literal["short", "medium", "long"]
Level = Literal["goal", "subgoal", "task", "action"]


@dataclass
class PlanNode:
    id: str
    level: Level
    title: str
    horizon_days: int
    budget_usd: float = 0.0
    success_criteria: dict[str, Any] = field(default_factory=dict)
    owner_signoff: bool = False
    children_ids: list[str] = field(default_factory=list)
    parent_id: str | None = None
    rationale: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "level": self.level,
            "title": self.title,
            "horizon_days": self.horizon_days,
            "budget_usd": round(self.budget_usd, 2),
            "success_criteria": self.success_criteria,
            "owner_signoff": self.owner_signoff,
            "children_ids": self.children_ids,
            "parent_id": self.parent_id,
            "rationale": self.rationale,
            "params": self.params,
        }


@dataclass
class Hierarchy:
    id: str
    goal_text: str
    root_id: str
    nodes: dict[str, PlanNode] = field(default_factory=dict)
    created_at: float = 0.0

    def add(self, node: PlanNode, parent_id: str | None = None) -> None:
        self.nodes[node.id] = node
        if parent_id:
            parent = self.nodes.get(parent_id)
            if parent is not None:
                parent.children_ids.append(node.id)
                node.parent_id = parent_id

    def children(self, node_id: str) -> list[PlanNode]:
        node = self.nodes.get(node_id)
        if not node:
            return []
        return [self.nodes[c] for c in node.children_ids if c in self.nodes]

    def leaves(self) -> list[PlanNode]:
        return [n for n in self.nodes.values() if not n.children_ids]

    def total_budget(self) -> float:
        return sum(n.budget_usd for n in self.nodes.values() if n.level == "action")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal_text": self.goal_text,
            "root_id": self.root_id,
            "created_at": self.created_at,
            "total_budget": round(self.total_budget(), 2),
            "node_count": len(self.nodes),
            "nodes": [n.as_dict() for n in self.nodes.values()],
        }


# ── Public API ───────────────────────────────────────────────

def decompose(goal_text: str) -> Hierarchy:
    """Turn a free-text goal into a four-level hierarchy.

    The decomposer matches the goal to a template based on keywords
    (revenue / AOV / multi-store / niche / efficiency). Each template
    has its own sub-goal set, task set, and default budgets; the
    planner (v3-D7) is called per-task to produce the leaf actions.
    """
    h = Hierarchy(
        id=f"hp_{uuid.uuid4().hex[:12]}",
        goal_text=goal_text.strip(),
        root_id="",
        created_at=time.time(),
    )
    if not h.goal_text:
        return h

    root = PlanNode(
        id="g_root",
        level="goal",
        title=goal_text.strip(),
        horizon_days=30,
        rationale="Top-level vision — owner-authored.",
    )
    h.root_id = root.id
    h.add(root)

    t = goal_text.lower()
    if any(k in t for k in ("revenue", "grow", "double", "lift sales")):
        _decompose_revenue(h, root)
    elif "aov" in t or "upsell" in t or "cross-sell" in t or "basket" in t:
        _decompose_aov(h, root)
    elif "multi-store" in t or "multi store" in t or "scale to" in t:
        _decompose_multi_store(h, root)
    elif "niche" in t or "pivot" in t or "test" in t:
        _decompose_niche_test(h, root)
    elif "efficiency" in t or "cost" in t or "reduce spend" in t:
        _decompose_efficiency(h, root)
    else:
        _decompose_generic(h, root)

    return h


# ── Template decomposers ────────────────────────────────────

def _decompose_revenue(h: Hierarchy, root: PlanNode) -> None:
    # 30-day revenue-growth template: 3 weekly sub-goals.
    root.success_criteria = {"metric": "revenue_30d", "target_pct": 20}
    for week in range(1, 4):
        sg = PlanNode(
            id=f"sg_w{week}", level="subgoal",
            title=f"Week {week}: grow revenue run-rate",
            horizon_days=7,
            rationale="weekly milestone splits a long-horizon goal",
            success_criteria={"metric": "revenue_weekly",
                              "target_pct": 7 * week},
        )
        h.add(sg, parent_id=root.id)
        _task_scale_winners(h, sg)
        _task_launch_new(h, sg)
        _task_kill_losers(h, sg)


def _decompose_aov(h: Hierarchy, root: PlanNode) -> None:
    root.success_criteria = {"metric": "aov", "target_pct": 15}
    sg = PlanNode(
        id="sg_aov", level="subgoal",
        title="Lift average order value across live catalog",
        horizon_days=14,
        success_criteria={"metric": "aov", "target_pct": 15},
    )
    h.add(sg, parent_id=root.id)
    _task_cross_sell(h, sg)
    _task_bundle(h, sg)
    _task_post_purchase(h, sg)


def _decompose_multi_store(h: Hierarchy, root: PlanNode) -> None:
    root.success_criteria = {"stores_live": 3}
    sg = PlanNode(
        id="sg_ms", level="subgoal",
        title="Replicate winning patterns to a second store",
        horizon_days=30,
        success_criteria={"stores_live": 2},
    )
    h.add(sg, parent_id=root.id)
    _task_share_learning(h, sg)
    _task_clone_catalog(h, sg)


def _decompose_niche_test(h: Hierarchy, root: PlanNode) -> None:
    root.success_criteria = {"metric": "launches_tested", "target": 5}
    sg = PlanNode(
        id="sg_niche", level="subgoal",
        title="Probe niche with 5 micro-launches",
        horizon_days=14,
        success_criteria={"launches": 5},
    )
    h.add(sg, parent_id=root.id)
    for i in range(1, 4):
        t = PlanNode(
            id=f"task_probe_{i}", level="task",
            title=f"Probe #{i}",
            horizon_days=3,
            budget_usd=30.0,
            rationale="cheap-and-fast test — single SKU with $20/day budget",
        )
        h.add(t, parent_id=sg.id)
        _action(h, t, kind="launch_product",
                params={"ad_budget_day": 20.0, "target_price": 24.99},
                cost=20.0 * 3, rationale="budget-safe launch")


def _decompose_efficiency(h: Hierarchy, root: PlanNode) -> None:
    root.success_criteria = {"metric": "cac", "target_pct": -20}
    sg = PlanNode(
        id="sg_eff", level="subgoal",
        title="Cut customer-acquisition cost 20 %",
        horizon_days=14,
        success_criteria={"metric": "cac", "target_pct": -20},
    )
    h.add(sg, parent_id=root.id)
    _task_kill_losers(h, sg)
    _task_reuse_creative(h, sg)


def _decompose_generic(h: Hierarchy, root: PlanNode) -> None:
    # Fallback: single subgoal that just calls the reasoner.
    sg = PlanNode(
        id="sg_reason", level="subgoal",
        title="Research the goal",
        horizon_days=1,
        rationale="free-form goal — start with reasoning chain",
    )
    h.add(sg, parent_id=root.id)
    t = PlanNode(
        id="task_reason", level="task",
        title="Run 4-phase reasoning",
        horizon_days=1,
        rationale="v1-D3 research → hypothesize → test → evaluate",
    )
    h.add(t, parent_id=sg.id)
    _action(h, t, kind="run_reasoning",
            params={"question": root.title},
            cost=0.02, rationale="single deep-reasoning pass")


# ── Task templates (reusable across goals) ──────────────────

def _task_scale_winners(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_scale_{subgoal.id}", level="task",
        title=f"Scale winners during {subgoal.title}",
        horizon_days=subgoal.horizon_days,
        budget_usd=120.0,
        rationale="double budgets on ROAS ≥ scale_threshold launches",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="scale_launch",
            params={"scale_factor": 2.0}, cost=120.0,
            rationale="evaluator-surfaced scale verdicts")


def _task_launch_new(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_launch_{subgoal.id}", level="task",
        title=f"Launch 2 new SKUs in {subgoal.title}",
        horizon_days=subgoal.horizon_days,
        budget_usd=60.0,
        rationale="fresh launches fuel the funnel",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="launch_product",
            params={"ad_budget_day": 20.0}, cost=20.0 * 3,
            rationale="budget-safe new launch")
    _action(h, t, kind="launch_product",
            params={"ad_budget_day": 20.0}, cost=20.0 * 3,
            rationale="budget-safe new launch")


def _task_kill_losers(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_kill_{subgoal.id}", level="task",
        title="Kill under-performers",
        horizon_days=subgoal.horizon_days,
        budget_usd=0.0,
        rationale="stop the bleeding before scaling",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="kill_launch", params={},
            cost=0.0,
            rationale="evaluator-surfaced kill verdicts")


def _task_cross_sell(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_crosssell_{subgoal.id}", level="task",
        title="Backfill related_product_ids metafield",
        horizon_days=3,
        rationale="AOV lever via storefront widget",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="add_cross_sell",
            params={"top_k": 4}, cost=0.0,
            rationale="scored related-products picker")


def _task_bundle(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_bundle_{subgoal.id}", level="task",
        title="Create 3-product bundles",
        horizon_days=5,
        owner_signoff=True,
        rationale="bundles typically outperform single-SKU margins",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="create_bundle",
            params={"discount_pct": 10}, cost=0.0,
            rationale="Shopify bundle object via API")


def _task_post_purchase(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_postpurch_{subgoal.id}", level="task",
        title="Post-purchase upsell offer",
        horizon_days=5,
        owner_signoff=True,
        rationale="highest-CVR upsell slot in the funnel",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="run_reasoning",
            params={"question": "which product should be offered post-purchase?"},
            cost=0.02, rationale="AI picks best match")


def _task_share_learning(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_share_{subgoal.id}", level="task",
        title="Share rules + strategies to new store",
        horizon_days=2,
        rationale="MultiStoreManager.share_learning already exists",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="run_reasoning",
            params={"question": "which rules transfer to a new store?"},
            cost=0.02,
            rationale="transfer_learner powers this")


def _task_clone_catalog(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_clone_{subgoal.id}", level="task",
        title="Clone top winners to the new store",
        horizon_days=7,
        owner_signoff=True,
        budget_usd=60.0,
        rationale="don't recreate from scratch; replicate proven SKUs",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="launch_product",
            params={"ad_budget_day": 20.0}, cost=60.0,
            rationale="clone winner into new store")


def _task_reuse_creative(h: Hierarchy, subgoal: PlanNode) -> None:
    t = PlanNode(
        id=f"task_reuse_{subgoal.id}", level="task",
        title="Reuse high-CTR creatives on new launches",
        horizon_days=4,
        rationale="winning creatives carry CTR signal",
    )
    h.add(t, parent_id=subgoal.id)
    _action(h, t, kind="run_reasoning",
            params={"question": "which creatives had CTR > 1% we can reuse?"},
            cost=0.02,
            rationale="reasoner extracts high-signal assets")


def _action(
    h: Hierarchy,
    task: PlanNode,
    kind: str,
    params: dict[str, Any],
    cost: float,
    rationale: str,
) -> PlanNode:
    n = PlanNode(
        id=f"a_{task.id}_{len(task.children_ids) + 1}",
        level="action",
        title=f"{kind}",
        horizon_days=task.horizon_days,
        budget_usd=cost,
        rationale=rationale,
        params={"kind": kind, **params},
    )
    h.add(n, parent_id=task.id)
    return n
