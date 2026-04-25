"""Goal decomposer — break a high-level goal into ordered subgoals.

Owners set goals in one sentence ("hit $10k/day", "launch new SKU in
15 min") but execution needs a *graph* of steps with dependencies.

goal_decomposer owns rule-based decomposition: a registry of
``DecompositionRule`` objects, each matching goals by regex or
key/value, produces a list of ``SubGoal`` nodes with explicit
``depends_on`` edges. The output ``Plan`` is a DAG ordered by
topological sort. Cycles raise immediately.

No LLM calls; adding new goal shapes = adding a new rule. Each rule
can also declare a "success_criterion" that ties back to a KPI +
threshold + direction, so assumption_ledger and predictive_alerter
can monitor progress after kickoff.

complements ``goal_compiler`` (which compiles a single goal into
runnable primitives) by producing a readable plan first so owners can
see what will happen. Pure stdlib, deterministic.
"""
from __future__ import annotations

import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.goal_decomposer")


@dataclass
class SubGoal:
    id: str
    name: str
    description: str
    depends_on: tuple[str, ...] = ()
    kpi: str = ""
    threshold: float | None = None
    direction: str = ""         # "above" / "below" / ""
    estimated_minutes: float = 0.0
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "depends_on": list(self.depends_on),
            "kpi": self.kpi,
            "threshold": self.threshold,
            "direction": self.direction,
            "estimated_minutes": round(self.estimated_minutes, 2),
            "rationale": self.rationale,
        }


@dataclass
class Plan:
    goal_text: str
    subgoals: list[SubGoal]
    order: list[str]            # topological order of ids
    rule_id: str
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal_text": self.goal_text,
            "subgoals": [s.as_dict() for s in self.subgoals],
            "order": list(self.order),
            "rule_id": self.rule_id,
            "notes": list(self.notes),
        }


@dataclass
class DecompositionRule:
    id: str
    pattern: str                 # regex over goal_text (case-insens)
    builder: Callable[
        [str, dict[str, Any]], list[SubGoal],
    ]
    description: str = ""
    priority: int = 100           # lower wins


def _toposort(
    subgoals: list[SubGoal],
) -> list[str]:
    """Kahn's algorithm. Raises ValueError on cycle."""
    id_set = {s.id for s in subgoals}
    in_deg: dict[str, int] = {s.id: 0 for s in subgoals}
    adj: dict[str, list[str]] = {s.id: [] for s in subgoals}
    for s in subgoals:
        for dep in s.depends_on:
            if dep not in id_set:
                raise ValueError(
                    f"subgoal {s.id} depends on unknown {dep}",
                )
            adj[dep].append(s.id)
            in_deg[s.id] += 1
    queue = [sid for sid, d in in_deg.items() if d == 0]
    # deterministic tie-break by name
    lookup = {s.id: s for s in subgoals}
    queue.sort(key=lambda sid: lookup[sid].name)
    order: list[str] = []
    while queue:
        sid = queue.pop(0)
        order.append(sid)
        for neighbor in adj[sid]:
            in_deg[neighbor] -= 1
            if in_deg[neighbor] == 0:
                queue.append(neighbor)
        queue.sort(key=lambda x: lookup[x].name)
    if len(order) != len(subgoals):
        raise ValueError("cycle in decomposition plan")
    return order


def _launch_sku_builder(
    goal_text: str, _params: dict[str, Any],
) -> list[SubGoal]:
    create = SubGoal(
        id="sg_create",
        name="create_product",
        description="Create Shopify product from source URL",
        estimated_minutes=5.0,
        rationale="needed before media & pricing",
    )
    media = SubGoal(
        id="sg_media",
        name="attach_media",
        description="Upload images + demo video",
        depends_on=("sg_create",),
        estimated_minutes=4.0,
    )
    price = SubGoal(
        id="sg_price",
        name="set_price",
        description="Set price bands + compare-at",
        depends_on=("sg_create",),
        estimated_minutes=1.0,
    )
    publish = SubGoal(
        id="sg_publish",
        name="publish",
        description="Mark product active + add to collection",
        depends_on=("sg_media", "sg_price"),
        estimated_minutes=1.0,
    )
    ad = SubGoal(
        id="sg_ad",
        name="launch_ad",
        description="Launch $20/day Meta ad with default audience",
        depends_on=("sg_publish",),
        kpi="ad_spend",
        threshold=20.0,
        direction="below",
        estimated_minutes=4.0,
    )
    return [create, media, price, publish, ad]


def _revenue_target_builder(
    _goal_text: str, params: dict[str, Any],
) -> list[SubGoal]:
    target = float(params.get("target_revenue", 10_000.0))
    find_winner = SubGoal(
        id="sg_winner",
        name="find_winner",
        description="Identify SKU with highest existing ROAS",
        estimated_minutes=15.0,
    )
    scale_budget = SubGoal(
        id="sg_scale",
        name="scale_budget",
        description="Raise daily spend in 15% steps on winner",
        depends_on=("sg_winner",),
        kpi="roas",
        threshold=1.5,
        direction="above",
        estimated_minutes=30.0,
    )
    price_test = SubGoal(
        id="sg_price_test",
        name="price_test",
        description="A/B price points to protect AOV",
        depends_on=("sg_winner",),
        estimated_minutes=60.0,
    )
    hold_target = SubGoal(
        id="sg_target",
        name="hold_target",
        description=f"Sustain daily revenue above ${target:,.0f}",
        depends_on=("sg_scale", "sg_price_test"),
        kpi="daily_revenue",
        threshold=target,
        direction="above",
        estimated_minutes=240.0,
    )
    return [find_winner, scale_budget, price_test, hold_target]


def _kill_underperformer_builder(
    _goal_text: str, params: dict[str, Any],
) -> list[SubGoal]:
    kpi = str(params.get("kpi", "roas"))
    threshold = float(params.get("threshold", 1.5))
    direction = str(params.get("direction", "below"))
    watch = SubGoal(
        id="sg_watch",
        name="watch_kpi",
        description=f"Watch {kpi} over 3-day window",
        kpi=kpi,
        threshold=threshold,
        direction=direction,
        estimated_minutes=4320.0,
    )
    kill = SubGoal(
        id="sg_kill",
        name="auto_kill",
        description=(
            f"Auto-kill campaign if {kpi} stays "
            f"{direction} {threshold}"
        ),
        depends_on=("sg_watch",),
        estimated_minutes=1.0,
    )
    return [watch, kill]


_DEFAULT_RULES: tuple[DecompositionRule, ...] = (
    DecompositionRule(
        id="launch_sku",
        pattern=r"(launch|list|publish|upload).*(product|sku|item)",
        builder=_launch_sku_builder,
        description="New product launch with ads",
        priority=10,
    ),
    DecompositionRule(
        id="revenue_target",
        pattern=(
            r"(hit|reach|achieve).*\$?[\d,]+.*(day|daily|"
            r"week|month|revenue)"
        ),
        builder=_revenue_target_builder,
        description="Revenue target pursuit",
        priority=20,
    ),
    DecompositionRule(
        id="kill_rule",
        pattern=r"(kill|pause|stop).*(if|when).*(roas|cpm|cvr)",
        builder=_kill_underperformer_builder,
        description="Kill underperformer guard",
        priority=30,
    ),
)


class GoalDecomposer:
    def __init__(
        self,
        *,
        rules: Iterable[DecompositionRule] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._rules: list[DecompositionRule] = []
        for r in (rules if rules is not None else _DEFAULT_RULES):
            self._rules.append(r)
        self._rules.sort(key=lambda r: r.priority)

    def register(self, rule: DecompositionRule) -> None:
        with self._lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: r.priority)

    def unregister(self, rule_id: str) -> bool:
        with self._lock:
            before = len(self._rules)
            self._rules = [
                r for r in self._rules if r.id != rule_id
            ]
            return len(self._rules) < before

    # ── Decompose ────────────────────────────────────────

    def decompose(
        self,
        goal_text: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> Plan:
        if not goal_text:
            raise ValueError("goal_text required")
        text = goal_text.strip()
        params = dict(params or {})
        with self._lock:
            rules = list(self._rules)
        matched: DecompositionRule | None = None
        for rule in rules:
            if re.search(
                rule.pattern, text, flags=re.IGNORECASE,
            ):
                matched = rule
                break
        if matched is None:
            # Fallback — single opaque subgoal
            placeholder = SubGoal(
                id=f"sg_{uuid.uuid4().hex[:6]}",
                name="owner_goal",
                description=text,
                rationale="no rule matched; manual execution",
            )
            return Plan(
                goal_text=text,
                subgoals=[placeholder],
                order=[placeholder.id],
                rule_id="",
                notes=["no rule matched"],
            )
        subgoals = matched.builder(text, params)
        if not subgoals:
            raise ValueError(
                f"rule {matched.id} produced empty subgoals",
            )
        order = _toposort(subgoals)
        return Plan(
            goal_text=text,
            subgoals=subgoals,
            order=order,
            rule_id=matched.id,
        )

    def rules(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "id": r.id,
                    "pattern": r.pattern,
                    "description": r.description,
                    "priority": r.priority,
                }
                for r in self._rules
            ]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "rules": len(self._rules),
                "rule_ids": sorted(r.id for r in self._rules),
            }
