"""Plan synthesizer — owner goal → executable action DAG.

Owners think in goals ("lift AOV 20 %", "cut ad spend in half",
"test a pet niche"). The reasoner (v1-D3) produces hypotheses; the
planner turns a hypothesis (or a raw goal) into a dependency graph
of actions the brain can actually execute, with:

  • estimated cost (USD per node, summed)
  • estimated win probability (composite skill confidence)
  • expected value (revenue impact from past similar runs)
  • dependencies between nodes so the daemon can topological-sort
    and execute in parallel where safe

Structure:

    goal → [ActionNode, ActionNode, ...]  where each ActionNode has
           {id, kind, params, depends_on[], cost_usd, win_prob, rationale}

Kinds currently recognised:

  launch_product   — run workflows/launch pipeline for a SKU
  kill_launch      — stop a running launch
  scale_launch     — double budget on a healthy launch
  add_cross_sell   — populate related-products metafield
  run_reasoning    — kick off a reason() chain for deeper study

The planner is deterministic: given the same goal + memory state it
produces the same graph. LLM intervention happens only when the
owner's goal text is free-form and we call the reasoner to convert
it into a canonical intent.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionNode:
    id: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    win_prob: float = 0.5
    expected_value_usd: float = 0.0
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "params": self.params,
            "depends_on": self.depends_on,
            "cost_usd": round(self.cost_usd, 2),
            "win_prob": round(self.win_prob, 3),
            "expected_value_usd": round(self.expected_value_usd, 2),
            "rationale": self.rationale,
        }


@dataclass
class Plan:
    goal: str
    id: str
    nodes: list[ActionNode] = field(default_factory=list)
    total_cost: float = 0.0
    aggregate_win_prob: float = 0.0
    expected_value: float = 0.0
    created_at: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "total_cost": round(self.total_cost, 2),
            "aggregate_win_prob": round(self.aggregate_win_prob, 3),
            "expected_value": round(self.expected_value, 2),
            "created_at": self.created_at,
            "nodes": [n.as_dict() for n in self.nodes],
        }


# ── Intent detection ────────────────────────────────────────

_KILL_TRIGGERS = ("kill", "stop", "cut", "pause", "end")
_SCALE_TRIGGERS = ("scale", "double", "ramp", "boost", "grow")
_LAUNCH_TRIGGERS = ("launch", "test", "pivot", "try", "introduce", "add")
_AOV_TRIGGERS = ("aov", "upsell", "cross-sell", "basket")


def synthesize(goal: str) -> Plan:
    """Turn a free-text goal into an action DAG."""
    plan = Plan(
        goal=goal.strip(),
        id=f"plan_{uuid.uuid4().hex[:12]}",
        created_at=time.time(),
    )
    if not plan.goal:
        return plan

    text = plan.goal.lower()
    if any(t in text for t in _KILL_TRIGGERS):
        _plan_kill(plan)
    elif any(t in text for t in _SCALE_TRIGGERS):
        _plan_scale(plan)
    elif any(t in text for t in _LAUNCH_TRIGGERS):
        _plan_launch(plan, text)
    elif any(t in text for t in _AOV_TRIGGERS):
        _plan_aov(plan)
    else:
        _plan_research(plan)

    _score(plan)
    return plan


# ── Plan templates ──────────────────────────────────────────

def _plan_kill(plan: Plan) -> None:
    """Owner wants to cut losers. Pull the evaluator's kill list and
    stage one kill_launch node per candidate; each has a sim_before
    prereq so the brain doesn't act blind."""
    try:
        from core.autonomous.launch_evaluator import evaluate
        report = evaluate()
        targets = report.kill_recommendations[:5]
    except Exception:
        targets = []

    if not targets:
        plan.nodes.append(ActionNode(
            id="research_why",
            kind="run_reasoning",
            rationale="no kill candidates — investigate what's healthy",
            cost_usd=0.02,
            win_prob=0.6,
            params={"question": plan.goal},
        ))
        return

    for s in targets:
        sim_id = f"sim_{s.launch_id[:10]}"
        kill_id = f"kill_{s.launch_id[:10]}"
        plan.nodes.append(ActionNode(
            id=sim_id, kind="simulate",
            params={"intervention": "kill_launch",
                    "launch_id": s.launch_id},
            depends_on=[],
            cost_usd=0.0,
            win_prob=0.95,
            rationale="Monte-Carlo estimate of net saved",
        ))
        plan.nodes.append(ActionNode(
            id=kill_id, kind="kill_launch",
            params={"launch_id": s.launch_id,
                    "reason": s.reason[:120]},
            depends_on=[sim_id],
            cost_usd=0.0,
            win_prob=0.85,
            expected_value_usd=float(s.ad_budget_day) * 3,
            rationale=f"ROAS {s.estimated_roas:.2f} < {s.kill_roas}",
        ))


def _plan_scale(plan: Plan) -> None:
    try:
        from core.autonomous.launch_evaluator import evaluate
        report = evaluate()
        targets = report.scale_recommendations[:5]
    except Exception:
        targets = []

    if not targets:
        plan.nodes.append(ActionNode(
            id="research_targets",
            kind="run_reasoning",
            params={"question": "which launches qualify for scaling?"},
            cost_usd=0.02, win_prob=0.6,
            rationale="no scale candidates currently qualified",
        ))
        return

    for s in targets:
        sim_id = f"sim_{s.launch_id[:10]}"
        scale_id = f"scale_{s.launch_id[:10]}"
        plan.nodes.append(ActionNode(
            id=sim_id, kind="simulate",
            params={"intervention": "scale_launch",
                    "launch_id": s.launch_id,
                    "scale_factor": 2.0},
            cost_usd=0.0, win_prob=0.95,
            rationale="project revenue at 2× budget",
        ))
        plan.nodes.append(ActionNode(
            id=scale_id, kind="scale_launch",
            params={"launch_id": s.launch_id,
                    "scale_factor": 2.0},
            depends_on=[sim_id],
            cost_usd=0.0, win_prob=0.75,
            expected_value_usd=float(s.estimated_roas * s.ad_budget_day * 3),
            rationale=f"ROAS {s.estimated_roas:.2f} ≥ {s.scale_roas}",
        ))


def _plan_launch(plan: Plan, text: str) -> None:
    # Detect niche hint
    niche = ""
    for tok in text.split():
        if tok.endswith("niche"):
            niche = tok.replace("niche", "").strip(" _-")
            break
    plan.nodes.append(ActionNode(
        id="research_winners",
        kind="run_reasoning",
        params={"question": f"what winning patterns apply to {niche or 'a new niche'}?"},
        cost_usd=0.02, win_prob=0.7,
        rationale="gather cross-niche transfer patterns",
    ))
    plan.nodes.append(ActionNode(
        id="launch_v1",
        kind="launch_product",
        params={"niche": niche, "target_price": 29.99,
                "ad_budget_day": 20.0, "copy_tone": "urgent"},
        depends_on=["research_winners"],
        cost_usd=25.0,
        win_prob=0.45,
        expected_value_usd=120.0,
        rationale="execute full launch pipeline with budget-safe defaults",
    ))
    plan.nodes.append(ActionNode(
        id="wait_horizon",
        kind="wait",
        params={"days": 3},
        depends_on=["launch_v1"],
        cost_usd=0.0, win_prob=1.0,
        rationale="observe 3-day ROAS before deciding",
    ))
    plan.nodes.append(ActionNode(
        id="verdict",
        kind="run_reasoning",
        params={"question": "was launch_v1 profitable? kill/scale/hold?"},
        depends_on=["wait_horizon"],
        cost_usd=0.02, win_prob=0.9,
        rationale="ROAS bucketer verdict + simulation-backed choice",
    ))


def _plan_aov(plan: Plan) -> None:
    plan.nodes.append(ActionNode(
        id="audit_products",
        kind="run_reasoning",
        params={"question": "which live products have no related_product_ids?"},
        cost_usd=0.02, win_prob=0.85,
        rationale="identify cross-sell gaps",
    ))
    plan.nodes.append(ActionNode(
        id="backfill_cross_sell",
        kind="add_cross_sell",
        params={"top_k": 4},
        depends_on=["audit_products"],
        cost_usd=0.0, win_prob=0.8,
        expected_value_usd=45.0,
        rationale="Related products lift AOV ~10-15 % per Shopify",
    ))


def _plan_research(plan: Plan) -> None:
    """Fallback: kick off the 4-phase reasoner on the goal."""
    plan.nodes.append(ActionNode(
        id="reason",
        kind="run_reasoning",
        params={"question": plan.goal},
        cost_usd=0.02, win_prob=0.65,
        rationale="free-form goal — route to reasoning chain",
    ))


# ── Scoring ──────────────────────────────────────────────────

def _score(plan: Plan) -> None:
    """Compute totals + aggregate win_prob (product of independent
    branches). Nodes that run in parallel contribute independently;
    nodes with dependencies are assumed sequential within their path."""
    plan.total_cost = sum(n.cost_usd for n in plan.nodes)
    plan.expected_value = sum(n.expected_value_usd for n in plan.nodes)
    if not plan.nodes:
        plan.aggregate_win_prob = 0.0
        return
    # Conservative: treat the plan's success as conjunction of all
    # nodes' probabilities. Owners can see individual w_p per node.
    prob = 1.0
    for n in plan.nodes:
        prob *= n.win_prob
    plan.aggregate_win_prob = prob
