"""Behaviour tree — hierarchical planner with selector/sequence/condition.

workflow_dag (v17) is a flat DAG: every node runs once. behaviour_tree
is the game-AI cousin: a tree where parent nodes (composites) decide
which child runs based on results. The four canonical node kinds:

  • Sequence(...children)  — run children in order; FAIL on first
                              failure; SUCCESS only if all succeed.
  • Selector(...children)  — try children in order; SUCCESS on first
                              success; FAIL only if all fail.
  • Parallel(...children)  — run all children; SUCCESS when ≥
                              ``required_successes`` succeed.
  • Inverter(child)        — flip SUCCESS/FAILURE.
  • Condition(predicate)   — leaf that runs a predicate over context.
  • Action(name, fn)       — leaf that runs a side-effecting function;
                              return BTStatus.

Each tick of ``tree.tick(context)`` returns a Status. Trees are
deterministic given context and pure-stdlib.

Why a behaviour tree on top of goal_graph + plan_search? Different
shape: BT is best for *reactive*, condition-gated playbooks where
the same fallback-and-rescue logic runs every cycle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.behaviour_tree")


class BTStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"


# ── Base node ────────────────────────────────────────────

class BTNode:
    name: str

    def tick(self, context: dict[str, Any]) -> BTStatus:
        raise NotImplementedError

    def as_dict(self) -> dict[str, Any]:
        return {"node": self.__class__.__name__, "name": self.name}


# ── Composite nodes ─────────────────────────────────────

@dataclass
class Sequence(BTNode):
    name: str
    children: list[BTNode] = field(default_factory=list)

    def tick(self, context: dict[str, Any]) -> BTStatus:
        for child in self.children:
            status = child.tick(context)
            if status == BTStatus.RUNNING:
                return BTStatus.RUNNING
            if status == BTStatus.FAILURE:
                return BTStatus.FAILURE
        return BTStatus.SUCCESS

    def as_dict(self) -> dict[str, Any]:
        return {
            "node": "Sequence",
            "name": self.name,
            "children": [c.as_dict() for c in self.children],
        }


@dataclass
class Selector(BTNode):
    name: str
    children: list[BTNode] = field(default_factory=list)

    def tick(self, context: dict[str, Any]) -> BTStatus:
        for child in self.children:
            status = child.tick(context)
            if status == BTStatus.RUNNING:
                return BTStatus.RUNNING
            if status == BTStatus.SUCCESS:
                return BTStatus.SUCCESS
        return BTStatus.FAILURE

    def as_dict(self) -> dict[str, Any]:
        return {
            "node": "Selector",
            "name": self.name,
            "children": [c.as_dict() for c in self.children],
        }


@dataclass
class Parallel(BTNode):
    name: str
    children: list[BTNode] = field(default_factory=list)
    required_successes: int = 1

    def tick(self, context: dict[str, Any]) -> BTStatus:
        successes = 0
        running = 0
        for child in self.children:
            status = child.tick(context)
            if status == BTStatus.SUCCESS:
                successes += 1
            elif status == BTStatus.RUNNING:
                running += 1
        if successes >= self.required_successes:
            return BTStatus.SUCCESS
        if running > 0:
            return BTStatus.RUNNING
        return BTStatus.FAILURE

    def as_dict(self) -> dict[str, Any]:
        return {
            "node": "Parallel",
            "name": self.name,
            "required_successes": self.required_successes,
            "children": [c.as_dict() for c in self.children],
        }


@dataclass
class Inverter(BTNode):
    name: str
    child: BTNode

    def tick(self, context: dict[str, Any]) -> BTStatus:
        status = self.child.tick(context)
        if status == BTStatus.SUCCESS:
            return BTStatus.FAILURE
        if status == BTStatus.FAILURE:
            return BTStatus.SUCCESS
        return BTStatus.RUNNING

    def as_dict(self) -> dict[str, Any]:
        return {
            "node": "Inverter",
            "name": self.name,
            "child": self.child.as_dict(),
        }


# ── Leaf nodes ──────────────────────────────────────────

@dataclass
class Condition(BTNode):
    name: str
    predicate: Callable[[dict[str, Any]], bool]

    def tick(self, context: dict[str, Any]) -> BTStatus:
        try:
            return (
                BTStatus.SUCCESS
                if bool(self.predicate(context))
                else BTStatus.FAILURE
            )
        except Exception as exc:
            logger.debug("condition %s raised: %s", self.name, exc)
            return BTStatus.FAILURE


@dataclass
class Action(BTNode):
    name: str
    fn: Callable[[dict[str, Any]], BTStatus | bool | None]

    def tick(self, context: dict[str, Any]) -> BTStatus:
        try:
            result = self.fn(context)
        except Exception as exc:
            logger.debug("action %s raised: %s", self.name, exc)
            return BTStatus.FAILURE
        if isinstance(result, BTStatus):
            return result
        if result is True:
            return BTStatus.SUCCESS
        if result is False or result is None:
            return BTStatus.FAILURE
        # Permissive: treat any truthy non-Status return as success
        return BTStatus.SUCCESS if result else BTStatus.FAILURE


# ── Tree wrapper ─────────────────────────────────────────

@dataclass
class BehaviourTree:
    name: str
    root: BTNode
    last_status: BTStatus | None = None
    tick_count: int = 0

    def tick(self, context: dict[str, Any]) -> BTStatus:
        status = self.root.tick(context)
        self.last_status = status
        self.tick_count += 1
        return status

    def reset_stats(self) -> None:
        self.last_status = None
        self.tick_count = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "root": self.root.as_dict(),
            "last_status": (
                self.last_status.value if self.last_status else None
            ),
            "tick_count": self.tick_count,
        }
