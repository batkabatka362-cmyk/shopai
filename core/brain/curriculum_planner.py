"""Curriculum planner — learn skills in prerequisite order.

Some skills are foundational; others build on them. Without a
curriculum the brain tries to learn advanced skills (promote_winner)
before mastering basic ones (detect_duplicate_product), then fails
and looks incompetent.

This module:

  1. Accepts skills + prerequisites as a DAG.
  2. Checks mastery per skill via an injectable callable
     (e.g. competence_model.should_defer turned inside out).
  3. Computes the *next skill to practice*: smallest-depth un-mastered
     skill whose prerequisites are all already mastered.
  4. Produces an ordered ``learning_path`` end-to-end for a goal skill,
     topologically sorted.
  5. Detects cycles + unreachable nodes and reports them.

Pure stdlib. Deterministic. Small (< 250 LOC).
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from utils.logger import get_logger


logger = get_logger("brain.curriculum_planner")


@dataclass
class SkillNode:
    name: str
    prerequisites: tuple[str, ...] = ()
    difficulty: int = 1     # tie-breaker — smaller first
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SkillNode.name required")
        if self.difficulty < 1:
            raise ValueError("difficulty must be ≥ 1")


@dataclass
class LearningPath:
    goal: str
    ordered: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    cycle: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "ordered": list(self.ordered),
            "unreachable": list(self.unreachable),
            "cycle": self.cycle,
        }


@dataclass
class NextSkillReport:
    recommended: str | None
    why: str
    depth: int
    depth_of_remaining: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommended": self.recommended,
            "why": self.why,
            "depth": self.depth,
            "depth_of_remaining": dict(self.depth_of_remaining),
        }


class CurriculumPlanner:
    def __init__(
        self,
        mastery_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._nodes: dict[str, SkillNode] = {}
        self._mastery_fn = mastery_fn

    # ── Registration ─────────────────────────────────────

    def add(self, node: SkillNode, overwrite: bool = False) -> None:
        if node.name in self._nodes and not overwrite:
            raise ValueError(
                f"skill {node.name!r} already registered",
            )
        self._nodes[node.name] = node

    def remove(self, name: str) -> bool:
        return self._nodes.pop(name, None) is not None

    def skills(self) -> list[SkillNode]:
        return list(self._nodes.values())

    # ── Mastery hook ─────────────────────────────────────

    def _mastered(self, name: str) -> bool:
        if self._mastery_fn is None:
            return False
        try:
            return bool(self._mastery_fn(name))
        except Exception as exc:
            logger.debug(
                "mastery_fn %s raised: %s", name, exc,
            )
            return False

    # ── Depth (distance from leaves) ─────────────────────

    def _depth(self, name: str, seen: set[str] | None = None) -> int:
        """Max depth below a node; leaves have depth 0. Detects
        cycles by returning -1 when traversal revisits a node."""
        if name not in self._nodes:
            return -2   # unknown
        seen = set(seen or ())
        if name in seen:
            return -1
        seen.add(name)
        node = self._nodes[name]
        if not node.prerequisites:
            return 0
        deepest = 0
        for pre in node.prerequisites:
            d = self._depth(pre, seen)
            if d < 0:
                return d
            if d + 1 > deepest:
                deepest = d + 1
        return deepest

    # ── Learning path ────────────────────────────────────

    def path_to(self, goal: str) -> LearningPath:
        if goal not in self._nodes:
            return LearningPath(
                goal=goal, ordered=[], unreachable=[goal],
            )
        # Kahn-style topo sort limited to ancestors of goal.
        visited: set[str] = set()
        stack = [goal]
        relevant: set[str] = set()
        unreachable: list[str] = []
        while stack:
            name = stack.pop()
            if name in visited:
                continue
            visited.add(name)
            if name not in self._nodes:
                unreachable.append(name)
                continue
            relevant.add(name)
            for pre in self._nodes[name].prerequisites:
                stack.append(pre)

        indegree: dict[str, int] = defaultdict(int)
        for n in relevant:
            indegree[n] = sum(
                1 for pre in self._nodes[n].prerequisites
                if pre in relevant
            )
        queue: deque[str] = deque(sorted(
            [n for n in relevant if indegree[n] == 0],
            key=lambda k: (self._nodes[k].difficulty, k),
        ))
        ordered: list[str] = []
        while queue:
            name = queue.popleft()
            ordered.append(name)
            # Any node that has this as a prereq
            for other in relevant:
                if name in self._nodes[other].prerequisites:
                    indegree[other] -= 1
                    if indegree[other] == 0:
                        queue.append(other)
            # Keep queue deterministic — sort the list backing the deque
            items = sorted(
                list(queue),
                key=lambda k: (self._nodes[k].difficulty, k),
            )
            queue.clear()
            queue.extend(items)

        cycle = len(ordered) != len(relevant)
        return LearningPath(
            goal=goal,
            ordered=ordered,
            unreachable=unreachable,
            cycle=cycle,
        )

    # ── Next skill ───────────────────────────────────────

    def next_skill(
        self,
        goal: str | None = None,
    ) -> NextSkillReport:
        """Pick the smallest-depth unmastered skill whose prerequisites
        are all mastered. If ``goal`` given, restrict to its ancestors."""
        if goal is not None:
            path = self.path_to(goal)
            if path.cycle:
                return NextSkillReport(
                    recommended=None,
                    why="cycle detected in prerequisites",
                    depth=-1,
                )
            if path.unreachable:
                return NextSkillReport(
                    recommended=None,
                    why=f"unknown prerequisites: {path.unreachable}",
                    depth=-1,
                )
            candidates = [
                n for n in path.ordered
                if not self._mastered(n)
            ]
        else:
            candidates = [
                name for name in self._nodes
                if not self._mastered(name)
            ]

        # Filter: all prerequisites already mastered
        ready: list[str] = []
        for name in candidates:
            prereqs = self._nodes[name].prerequisites
            if all(self._mastered(p) for p in prereqs):
                ready.append(name)

        if not ready:
            return NextSkillReport(
                recommended=None,
                why="no skill is ready to practice",
                depth=-1,
                depth_of_remaining={
                    name: self._depth(name)
                    for name in candidates
                },
            )

        ready.sort(
            key=lambda n: (
                self._depth(n),
                self._nodes[n].difficulty,
                n,
            ),
        )
        chosen = ready[0]
        return NextSkillReport(
            recommended=chosen,
            why=(
                f"all {len(self._nodes[chosen].prerequisites)} "
                "prerequisite(s) mastered"
            ),
            depth=self._depth(chosen),
            depth_of_remaining={
                name: self._depth(name) for name in candidates
            },
        )

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        mastered = sum(
            1 for n in self._nodes if self._mastered(n)
        )
        return {
            "skills": len(self._nodes),
            "mastered": mastered,
            "remaining": len(self._nodes) - mastered,
        }
