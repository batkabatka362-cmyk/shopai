"""Decision rationale builder — structured 'because...' tree.

Every decision has a *why*. CLAUDE.md §4b/H: "every action must be
explainable; magic decisions fail audits". This module builds a
nested ``RationaleNode`` tree tying the decision together:

    decision
    ├── matched_rule(id=...)
    │   └── evidence(src=order_ledger, weight=0.8)
    ├── matched_case(id=...)
    └── safety_gate(passed, cap=0.15)

Each node has:

  • kind          — rule / case / evidence / gate / utility / ...
  • headline      — one short sentence
  • references    — pointers to other memory
  • weight        — contribution to the final decision (0..1)
  • children      — nested sub-rationale

Serialisation produces a Markdown bullet tree for owner reading and
a JSON structure for downstream logging. Complements
``decision_audit_trail`` (which records *what* happened) by focusing
on *why* it happened in a structured, nested form owners can browse.

Pure stdlib, deterministic.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.decision_rationale_builder")


Kind = Literal[
    "rule", "case", "evidence", "gate", "utility",
    "heuristic", "owner_override", "assumption", "note",
]


@dataclass
class RationaleNode:
    id: str
    kind: Kind
    headline: str
    weight: float              # 0..1 contribution
    references: tuple[str, ...] = ()
    children: list["RationaleNode"] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "headline": self.headline,
            "weight": round(self.weight, 4),
            "references": list(self.references),
            "children": [
                c.as_dict() for c in self.children
            ],
        }

    def as_markdown(self, *, depth: int = 0) -> str:
        indent = "  " * depth
        refs = (
            f" [{', '.join(self.references)}]"
            if self.references else ""
        )
        weight_tag = (
            f" (w={self.weight:.2f})"
            if 0.0 < self.weight < 1.0 else ""
        )
        lines = [
            f"{indent}- **{self.kind}**: {self.headline}"
            f"{weight_tag}{refs}",
        ]
        for child in self.children:
            lines.append(
                child.as_markdown(depth=depth + 1),
            )
        return "\n".join(lines)


@dataclass
class Rationale:
    decision_id: str
    summary: str
    root: RationaleNode
    ts: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "summary": self.summary,
            "root": self.root.as_dict(),
            "ts": self.ts,
        }

    def as_markdown(self) -> str:
        return (
            f"## Decision: {self.summary}\n"
            f"_id: {self.decision_id}_\n\n"
            f"{self.root.as_markdown()}"
        )


class DecisionRationaleBuilder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, Rationale] = {}
        # decision_id → rationale being constructed
        self._archive: dict[str, Rationale] = {}

    # ── Build ────────────────────────────────────────────

    def start(
        self,
        *,
        decision_id: str,
        summary: str,
    ) -> Rationale:
        if not decision_id:
            raise ValueError("decision_id required")
        if not summary:
            raise ValueError("summary required")
        root = RationaleNode(
            id=uuid.uuid4().hex,
            kind="note",
            headline=summary,
            weight=1.0,
        )
        rationale = Rationale(
            decision_id=str(decision_id),
            summary=str(summary),
            root=root,
            ts=time.time(),
        )
        with self._lock:
            if decision_id in self._active:
                raise ValueError(
                    f"decision {decision_id!r} already started",
                )
            self._active[decision_id] = rationale
        return rationale

    def add(
        self,
        decision_id: str,
        *,
        kind: Kind,
        headline: str,
        weight: float = 0.5,
        references: Iterable[str] = (),
        parent_id: str | None = None,
    ) -> RationaleNode:
        if not headline:
            raise ValueError("headline required")
        if not 0.0 <= weight <= 1.0:
            raise ValueError("weight must be in [0, 1]")
        node = RationaleNode(
            id=uuid.uuid4().hex,
            kind=kind,
            headline=headline,
            weight=float(weight),
            references=tuple(
                str(r) for r in references if r
            ),
        )
        with self._lock:
            rationale = self._active.get(decision_id)
            if rationale is None:
                raise ValueError(
                    f"decision {decision_id!r} not started",
                )
            parent = (
                self._find_node(rationale.root, parent_id)
                if parent_id else rationale.root
            )
            if parent is None:
                raise ValueError(
                    f"parent {parent_id!r} not in tree",
                )
            parent.children.append(node)
        return node

    def commit(
        self,
        decision_id: str,
    ) -> Rationale:
        with self._lock:
            rationale = self._active.pop(decision_id, None)
            if rationale is None:
                raise ValueError(
                    f"decision {decision_id!r} not started",
                )
            self._archive[decision_id] = rationale
        return rationale

    def abandon(self, decision_id: str) -> bool:
        with self._lock:
            return (
                self._active.pop(decision_id, None) is not None
            )

    def _find_node(
        self, root: RationaleNode, node_id: str,
    ) -> RationaleNode | None:
        if root.id == node_id:
            return root
        for child in root.children:
            found = self._find_node(child, node_id)
            if found is not None:
                return found
        return None

    # ── Queries ──────────────────────────────────────────

    def get(
        self, decision_id: str,
    ) -> Rationale | None:
        with self._lock:
            return (
                self._active.get(decision_id)
                or self._archive.get(decision_id)
            )

    def recent(self, *, limit: int = 20) -> list[Rationale]:
        with self._lock:
            items = list(self._archive.values())
        items.sort(key=lambda r: -r.ts)
        return items[: max(1, int(limit))]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "in_progress": len(self._active),
                "archived": len(self._archive),
            }

    def reset(self) -> int:
        with self._lock:
            n = len(self._active) + len(self._archive)
            self._active.clear()
            self._archive.clear()
        return n
