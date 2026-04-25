"""Task prioritizer — given many pending items, pick what to do first.

Each cycle the brain has:
  • goal_graph open goals
  • action_queue pending actions
  • commitment_register urgent commitments
  • curiosity probes
  • invariant breaches that need recovery

Nothing currently orders them against each other. The task
prioritizer accepts heterogeneous ``Task`` records (each with a
score, deadline, blast radius, dependency count) and emits a single
ranked list with a transparent score decomposition:

    score = base_value
            + urgency_bonus(deadline)
            + blast_penalty(radius)
            - dep_penalty(open_dependencies)
            - cost_penalty(cost_usd)

Pure stdlib, deterministic, no side effects. Works on the *caller-
supplied* Task list; this module is not a registry.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from utils.logger import get_logger


logger = get_logger("brain.task_prioritizer")


@dataclass
class Task:
    id: str
    kind: str                 # "goal" | "action" | "commitment" | ...
    base_value: float = 1.0
    deadline_ts: float | None = None
    blast_radius: int = 1
    open_dependencies: int = 0
    cost_usd: float = 0.0
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Task.id required")
        if not self.kind:
            raise ValueError("Task.kind required")
        if self.blast_radius < 1:
            raise ValueError("blast_radius must be ≥ 1")
        if self.open_dependencies < 0:
            raise ValueError("open_dependencies must be ≥ 0")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must be ≥ 0")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "base_value": round(self.base_value, 4),
            "deadline_ts": self.deadline_ts,
            "blast_radius": self.blast_radius,
            "open_dependencies": self.open_dependencies,
            "cost_usd": round(self.cost_usd, 4),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }


@dataclass
class PrioritizedTask:
    task: Task
    score: float
    urgency_bonus: float
    blast_penalty: float
    dep_penalty: float
    cost_penalty: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.as_dict(),
            "score": round(self.score, 4),
            "urgency_bonus": round(self.urgency_bonus, 4),
            "blast_penalty": round(self.blast_penalty, 4),
            "dep_penalty": round(self.dep_penalty, 4),
            "cost_penalty": round(self.cost_penalty, 4),
        }


# ── Default weights ──────────────────────────────────────

_DEFAULT_WEIGHTS = {
    "urgency_weight": 0.6,        # scales deadline pressure
    "blast_penalty_per_order": 0.1,  # penalty per order-of-magnitude
                                     # of blast radius beyond 1
    "dep_penalty_per_open": 0.2,
    "cost_scale_usd": 100.0,
}


class TaskPrioritizer:
    def __init__(
        self,
        *,
        urgency_weight: float = _DEFAULT_WEIGHTS["urgency_weight"],
        blast_penalty_per_order: float = _DEFAULT_WEIGHTS[
            "blast_penalty_per_order"
        ],
        dep_penalty_per_open: float = _DEFAULT_WEIGHTS[
            "dep_penalty_per_open"
        ],
        cost_scale_usd: float = _DEFAULT_WEIGHTS["cost_scale_usd"],
    ) -> None:
        if urgency_weight < 0 or blast_penalty_per_order < 0:
            raise ValueError(
                "urgency_weight / blast_penalty_per_order must be ≥ 0",
            )
        if dep_penalty_per_open < 0:
            raise ValueError("dep_penalty_per_open must be ≥ 0")
        if cost_scale_usd <= 0:
            raise ValueError("cost_scale_usd must be positive")
        self._urgency_w = float(urgency_weight)
        self._blast_per_order = float(blast_penalty_per_order)
        self._dep_per_open = float(dep_penalty_per_open)
        self._cost_scale = float(cost_scale_usd)

    # ── Scoring components ───────────────────────────────

    def _urgency_bonus(
        self, deadline_ts: float | None, now: float,
    ) -> float:
        if deadline_ts is None:
            return 0.0
        # Exponential ramp as deadline approaches (1 hour = 0.5)
        seconds_left = max(-86_400.0, deadline_ts - now)
        if seconds_left <= 0:
            # Overdue — clamp bonus to a large but finite value
            return self._urgency_w * 2.0
        # 0 hours → urgency_w, 24 hours → urgency_w × 0.25
        hours_left = seconds_left / 3600.0
        return self._urgency_w * (1.0 / (1.0 + hours_left))

    def _blast_penalty(self, blast: int) -> float:
        # log-style: blast_radius N → penalty × log10(N)
        # (clamped so blast=1 contributes 0)
        import math
        if blast <= 1:
            return 0.0
        return self._blast_per_order * math.log10(blast)

    def _dep_penalty(self, open_deps: int) -> float:
        return self._dep_per_open * float(open_deps)

    def _cost_penalty(self, cost_usd: float) -> float:
        return min(1.0, cost_usd / self._cost_scale)

    # ── Prioritize ───────────────────────────────────────

    def prioritize(
        self,
        tasks: Iterable[Task],
        *,
        now: float | None = None,
        top_k: int | None = None,
    ) -> list[PrioritizedTask]:
        if top_k is not None and top_k < 1:
            raise ValueError("top_k must be ≥ 1 when provided")
        now_ts = float(now if now is not None else time.time())
        out: list[PrioritizedTask] = []
        for task in tasks:
            urgency = self._urgency_bonus(task.deadline_ts, now_ts)
            blast = self._blast_penalty(task.blast_radius)
            deps = self._dep_penalty(task.open_dependencies)
            cost = self._cost_penalty(task.cost_usd)
            score = (
                float(task.base_value)
                + urgency
                - blast
                - deps
                - cost
            )
            out.append(PrioritizedTask(
                task=task,
                score=score,
                urgency_bonus=urgency,
                blast_penalty=blast,
                dep_penalty=deps,
                cost_penalty=cost,
            ))
        out.sort(key=lambda p: -p.score)
        if top_k is not None:
            out = out[:top_k]
        return out

    def best(
        self,
        tasks: Iterable[Task],
        *,
        now: float | None = None,
    ) -> PrioritizedTask | None:
        ranked = self.prioritize(tasks, now=now, top_k=1)
        return ranked[0] if ranked else None

    # ── Stats ────────────────────────────────────────────

    def config(self) -> dict[str, Any]:
        return {
            "urgency_weight": self._urgency_w,
            "blast_penalty_per_order": self._blast_per_order,
            "dep_penalty_per_open": self._dep_per_open,
            "cost_scale_usd": self._cost_scale,
        }
