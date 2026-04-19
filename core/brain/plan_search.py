"""Plan search — A* forward search to reach a goal state.

workflow_dag runs a hand-crafted graph of tasks. Real planning is
different: *given* a start state, a goal predicate, and a library of
Actions (each with preconditions, effects, cost), find the shortest
action sequence that reaches the goal.

Model:

    state     = frozendict-like mapping of key → value
    action    = Action(name, preconditions, effects, cost, heuristic)
    goal      = predicate(state) → bool

``search(start, goal_fn, actions, max_expansions=1000)`` returns a
``Plan`` with the action sequence and cumulative cost, or None when
no plan is found in budget.

Uses A* with a simple admissible heuristic: user-supplied or
``lambda s: 0``. Pure stdlib. Deterministic.
"""
from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


StateDict = dict[str, Any]
GoalFn = Callable[[StateDict], bool]
HeuristicFn = Callable[[StateDict], float]


def _freeze(s: StateDict) -> tuple[tuple[str, Any], ...]:
    """Hashable projection of a state for the visited set."""
    return tuple(sorted(
        (k, _hashable(v)) for k, v in s.items()
    ))


def _hashable(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return tuple(_hashable(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted(
            (k, _hashable(vv)) for k, vv in v.items()
        ))
    if isinstance(v, set):
        return ("__set__", tuple(sorted(_hashable(x) for x in v)))
    return v


@dataclass
class Action:
    name: str
    preconditions: Callable[[StateDict], bool]
    effects: Callable[[StateDict], StateDict]
    cost: float = 1.0

    def applicable(self, state: StateDict) -> bool:
        try:
            return bool(self.preconditions(state))
        except Exception:
            return False

    def apply(self, state: StateDict) -> StateDict:
        return dict(self.effects(state))


@dataclass
class Plan:
    actions: list[str]
    cost: float
    expansions: int
    final_state: StateDict = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "actions": list(self.actions),
            "cost": round(self.cost, 4),
            "expansions": self.expansions,
            "length": len(self.actions),
        }


def search(
    start: StateDict,
    goal_fn: GoalFn,
    actions: Iterable[Action],
    *,
    heuristic: HeuristicFn | None = None,
    max_expansions: int = 1_000,
    max_plan_length: int = 50,
) -> Plan | None:
    """A* plan search. Returns None when no plan fits the budget."""
    actions = list(actions)
    # Empty-plan answer: goal may already be met at start.
    if goal_fn(dict(start)):
        return Plan(
            actions=[], cost=0.0, expansions=0,
            final_state=dict(start),
        )
    if not actions:
        return None
    h = heuristic or (lambda _s: 0.0)
    counter = itertools.count()

    # Priority queue: (f, tie, g, state, path)
    frontier: list[tuple[float, int, float, StateDict, list[str]]] = []
    start_h = float(h(start))
    heapq.heappush(
        frontier,
        (start_h, next(counter), 0.0, dict(start), []),
    )
    visited: dict[tuple[tuple[str, Any], ...], float] = {
        _freeze(start): 0.0,
    }
    expansions = 0

    while frontier and expansions < max_expansions:
        f, _, g, state, path = heapq.heappop(frontier)
        expansions += 1

        if goal_fn(state):
            return Plan(
                actions=list(path), cost=g,
                expansions=expansions, final_state=dict(state),
            )

        if len(path) >= max_plan_length:
            continue

        for a in actions:
            if not a.applicable(state):
                continue
            try:
                new_state = a.apply(state)
            except Exception:
                continue
            key = _freeze(new_state)
            new_g = g + float(a.cost)
            prior_g = visited.get(key)
            if prior_g is not None and prior_g <= new_g:
                continue
            visited[key] = new_g
            new_h = float(h(new_state))
            heapq.heappush(
                frontier,
                (new_g + new_h, next(counter), new_g,
                 new_state, path + [a.name]),
            )
    return None


# ── Helpers for common patterns ────────────────────────────

def predicate_goal(target: dict[str, Any]) -> GoalFn:
    """Goal function that requires every key in target to be present
    and equal in the state."""
    def _pred(s: StateDict) -> bool:
        for k, v in target.items():
            if s.get(k) != v:
                return False
        return True
    return _pred


def delta_heuristic(target: dict[str, Any]) -> HeuristicFn:
    """Admissible: count of target keys not yet satisfied."""
    def _h(s: StateDict) -> float:
        unmet = 0
        for k, v in target.items():
            if s.get(k) != v:
                unmet += 1
        return float(unmet)
    return _h
