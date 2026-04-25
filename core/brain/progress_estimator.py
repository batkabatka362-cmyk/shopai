"""Progress estimator — % complete per goal with pace + ETA.

goal_agenda (v6-D1) tracks goal state; subgoal_discovery (v11-D6)
mines reusable patterns. Neither tells the owner 'you're 40%
through this goal, on pace to finish next Tuesday'. Progress
estimator owns that narrative.

Each Goal takes a list of Milestones with weights (sum = 100).
Each milestone has {name, weight, done, completed_at?, due_at?}.
The estimator computes:

  percent_complete = Σ weight * (1 if done else 0)
  pace             — milestones per day over the last week
  eta_days         — remaining weight / recent pace
  health           — "on_track" | "at_risk" | "stalled" | "done"

Also surfaces `blocked_milestones` when a due_at is in the past
without done=True — classic stalled work detector.

Pure stdlib math. No LLM. Deterministic given a fixed reference
``now``.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal


Health = Literal["done", "on_track", "at_risk", "stalled"]


@dataclass
class Milestone:
    name: str
    weight: float           # 0..100, goal's weights should sum to 100
    done: bool = False
    completed_at: float | None = None
    due_at: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "weight": round(self.weight, 2),
            "done": self.done,
            "completed_at": self.completed_at,
            "due_at": self.due_at,
        }


@dataclass
class GoalProgress:
    goal_id: str
    percent_complete: float
    pace_per_day: float
    eta_days: float | None
    health: Health
    blocked_milestones: list[str] = field(default_factory=list)
    milestones_done: int = 0
    total_milestones: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "percent_complete": round(self.percent_complete, 2),
            "pace_per_day": round(self.pace_per_day, 3),
            "eta_days": (round(self.eta_days, 2)
                          if self.eta_days is not None else None),
            "health": self.health,
            "blocked_milestones": list(self.blocked_milestones),
            "milestones_done": self.milestones_done,
            "total_milestones": self.total_milestones,
        }


# ── Estimator ──────────────────────────────────────────────

def estimate(
    goal_id: str,
    milestones: Iterable[Milestone | dict[str, Any]],
    *,
    now: float | None = None,
    pace_window_days: float = 7.0,
) -> GoalProgress:
    now = now or time.time()
    coerced: list[Milestone] = []
    for m in milestones:
        if isinstance(m, Milestone):
            coerced.append(m)
        elif isinstance(m, dict):
            coerced.append(Milestone(
                name=str(m.get("name", "?")),
                weight=float(m.get("weight", 0)),
                done=bool(m.get("done", False)),
                completed_at=(
                    float(m["completed_at"])
                    if m.get("completed_at") else None
                ),
                due_at=(
                    float(m["due_at"])
                    if m.get("due_at") else None
                ),
            ))
    if not coerced:
        return GoalProgress(
            goal_id=goal_id,
            percent_complete=0.0,
            pace_per_day=0.0,
            eta_days=None,
            health="stalled",
            blocked_milestones=[],
        )

    total_weight = sum(max(0.0, m.weight) for m in coerced)
    done_weight = sum(
        max(0.0, m.weight) for m in coerced if m.done
    )
    percent = (
        100.0 * done_weight / total_weight
        if total_weight > 0 else 0.0
    )

    # Pace: milestones completed in the last ``pace_window_days``
    window_start = now - pace_window_days * 86_400
    recent_done = sum(
        1 for m in coerced
        if m.done and m.completed_at
        and m.completed_at >= window_start
    )
    pace = recent_done / pace_window_days if pace_window_days > 0 else 0.0

    remaining = sum(
        1 for m in coerced if not m.done
    )
    eta: float | None = None
    if percent >= 100.0:
        eta = 0.0
    elif pace > 0 and remaining > 0:
        eta = remaining / pace

    # Blocked milestones: not done AND past due
    blocked = [
        m.name for m in coerced
        if not m.done and m.due_at is not None and m.due_at < now
    ]

    health = _classify(percent, pace, blocked, remaining)
    return GoalProgress(
        goal_id=goal_id,
        percent_complete=percent,
        pace_per_day=pace,
        eta_days=eta,
        health=health,
        blocked_milestones=blocked,
        milestones_done=sum(1 for m in coerced if m.done),
        total_milestones=len(coerced),
    )


def _classify(
    percent: float, pace: float,
    blocked: list[str], remaining: int,
) -> Health:
    if percent >= 100.0 or remaining == 0:
        return "done"
    if blocked:
        return "stalled" if pace == 0 else "at_risk"
    if pace == 0:
        return "stalled"
    return "on_track"


# ── Convenience ─────────────────────────────────────────────

def estimate_batch(
    goals: dict[str, Iterable[Milestone | dict[str, Any]]],
    *,
    now: float | None = None,
) -> list[GoalProgress]:
    """Estimate many goals at once; return sorted by health
    (stalled first so the urgent list is on top)."""
    order = {"stalled": 0, "at_risk": 1, "on_track": 2, "done": 3}
    reports = [
        estimate(gid, ms, now=now) for gid, ms in goals.items()
    ]
    reports.sort(key=lambda g: (order.get(g.health, 9),
                                  -len(g.blocked_milestones)))
    return reports
