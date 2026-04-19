"""Memory walker — typed graph traversal over the ontology.

The ontology (v7-D5) stores typed entities + triples. Retrieving
a single fact is a query; answering structural questions ("which
launches in the audio niche supplied by China scaled?") needs
multi-hop traversal.

MemoryWalker offers:

  • neighbors(entity_id, predicate=?) — one-hop fan-out.
  • walk(start, pattern) — multi-hop along a named predicate path.
    Pattern is a list of ``(predicate, direction)`` tuples where
    direction ∈ {"out", "in"}.
  • find(start_type, pattern, target_type) — entities reachable
    from any entity of ``start_type`` via ``pattern`` landing on
    ``target_type``. Returns the set of target ids.
  • answer(question) — a tiny structural-question matcher that
    recognises phrases like "which X supplied by Y" and converts
    them to walks automatically.

Each walk is capped by ``max_depth`` (default 4) and
``max_nodes`` (default 500) so the traversal can't run forever.
Visited-set dedups prevent cycles from blowing memory up.

Uses only the ontology singleton + its SQLite; no LLM.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from core.memory.ontology import Ontology, ontology


Direction = Literal["out", "in"]


@dataclass
class WalkStep:
    predicate: str
    direction: Direction


@dataclass
class WalkResult:
    start: str
    pattern: list[WalkStep]
    reached: list[str] = field(default_factory=list)
    visited: int = 0
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "pattern": [{"predicate": s.predicate,
                          "direction": s.direction}
                         for s in self.pattern],
            "reached": self.reached,
            "visited": self.visited,
            "truncated": self.truncated,
        }


class MemoryWalker:
    def __init__(
        self,
        ont: Ontology | None = None,
        max_depth: int = 4,
        max_nodes: int = 500,
    ) -> None:
        self._ont = ont or ontology()
        self._max_depth = int(max_depth)
        self._max_nodes = int(max_nodes)

    # ── One-hop ─────────────────────────────────────────────

    def neighbors(
        self,
        entity_id: str,
        predicate: str | None = None,
        direction: Direction = "out",
    ) -> list[str]:
        """Return ids reachable in one hop.

        ``direction="out"`` → where entity_id is the subject.
        ``direction="in"``  → where entity_id is the object."""
        if direction == "out":
            triples = self._ont.query(
                subject=entity_id, predicate=predicate,
            )
            return [t.object for t in triples]
        triples = self._ont.query(
            predicate=predicate, obj=entity_id,
        )
        return [t.subject for t in triples]

    # ── Multi-hop walk ─────────────────────────────────────

    def walk(
        self, start: str, pattern: Iterable[WalkStep | tuple[str, Direction]],
    ) -> WalkResult:
        steps: list[WalkStep] = []
        for s in pattern:
            if isinstance(s, WalkStep):
                steps.append(s)
            else:
                p, d = s
                steps.append(WalkStep(predicate=p, direction=d))
        if len(steps) > self._max_depth:
            steps = steps[: self._max_depth]
        frontier: deque[str] = deque([start])
        visited: set[str] = {start}
        for step in steps:
            next_frontier: set[str] = set()
            while frontier:
                node = frontier.popleft()
                for nxt in self.neighbors(
                    node, predicate=step.predicate,
                    direction=step.direction,
                ):
                    if nxt not in visited and len(visited) < self._max_nodes:
                        visited.add(nxt)
                        next_frontier.add(nxt)
            frontier = deque(next_frontier)
            if len(visited) >= self._max_nodes:
                break
        return WalkResult(
            start=start,
            pattern=steps,
            reached=sorted(frontier),
            visited=len(visited),
            truncated=len(visited) >= self._max_nodes,
        )

    # ── Find by types ─────────────────────────────────────

    def find(
        self,
        start_type: str,
        pattern: Iterable[WalkStep | tuple[str, Direction]],
        target_type: str | None = None,
    ) -> set[str]:
        """All target entities reachable from any start_type source
        via ``pattern``. If ``target_type`` is given, filter to
        entities with that (sub)type."""
        starts = self._ont.entities_of_type(
            start_type, include_subtypes=True,
        )
        targets: set[str] = set()
        for start in starts:
            result = self.walk(start.id, pattern)
            if target_type:
                for eid in result.reached:
                    if self._ont.is_a(eid, target_type):
                        targets.add(eid)
            else:
                targets.update(result.reached)
        return targets

    # ── Simple question matcher ────────────────────────────

    def answer(self, question: str) -> dict[str, Any]:
        """Lightweight NL → structured walk. Recognises patterns like:

            "which PRODUCTS have supplier in China"
            "list launches that are PRODUCTS"

        Returns a dict with ``{matched_pattern, answer_ids}`` or
        ``{error: ...}`` if nothing matched. This is intentionally
        tiny; a full NL layer is out of scope — this one is for
        deterministic dashboard shortcuts."""
        q = question.lower().strip()
        # Pattern 1: "which <TYPE> supplied by <id>"
        for marker in (" supplied by ", " made by "):
            if marker in q:
                head, tail = q.split(marker, 1)
                target_type = _pluck_type(head)
                supplier_id = tail.split()[0].rstrip("?.,")
                if target_type and supplier_id:
                    walker_pattern = [
                        WalkStep(predicate="supplied_by",
                                 direction="in"),
                    ]
                    result = self.walk(supplier_id, walker_pattern)
                    filtered = [
                        r for r in result.reached
                        if self._ont.is_a(r, target_type.capitalize())
                    ]
                    return {
                        "matched_pattern": "supplied_by",
                        "target_type": target_type,
                        "supplier": supplier_id,
                        "answer_ids": sorted(filtered),
                    }
        # Pattern 2: "list <TYPE>" (all instances including subtypes)
        if q.startswith("list "):
            target_type = _pluck_type(q[5:])
            if target_type:
                ents = self._ont.entities_of_type(
                    target_type.capitalize(), include_subtypes=True,
                )
                return {
                    "matched_pattern": "list_type",
                    "target_type": target_type,
                    "answer_ids": sorted(e.id for e in ents),
                }
        return {"error": "no matching pattern"}


def _pluck_type(text: str) -> str | None:
    """Strip common prefixes like 'which ' / 'the ' / trailing 's'."""
    words = text.strip().split()
    if not words:
        return None
    skip = {"which", "all", "every", "the", "list", "show", "any",
            "find", "tell", "me"}
    while words and words[0] in skip:
        words = words[1:]
    if not words:
        return None
    head = words[0]
    # Naive plural → singular: "launches" → "launch", "niches" → "niche".
    if head.endswith("es"):
        head = head[:-2]
    elif head.endswith("s"):
        head = head[:-1]
    return head or None
