"""Decision trace — every decision carries its own evidence DAG.

CLAUDE.md §4b.H (observability) says "every action explainable".
Today rules + strategies emit ``narrative`` strings but there's no
structured audit trail. A kill verdict says "ROAS < 1.5" but
doesn't link the *exact* memory rows, facts, and simulations that
led to it.

DecisionTrace fixes that: every decision builds a structured
evidence DAG as it runs. Nodes carry a kind (memory / fact /
simulation / skill / rule / feedback / narrative), a reference to
the underlying object, a weight (how much it shaped the outcome),
and a rationale. The trace persists as a first-class memory event
so the oracle / chat can retrieve + quote the exact evidence behind
any past decision.

Usage::

    from core.brain.decision_trace import Trace

    trace = Trace(goal="kill launch X")
    trace.cite(kind="memory", ref_id=42, weight=0.3,
               note="prior kill verdict with similar ROAS drop")
    trace.cite(kind="fact", ref_id="roas.kill_threshold", weight=0.6,
               note="threshold 1.5 applied")
    trace.cite(kind="simulation", ref=sim_result.as_dict(), weight=0.5,
               note="MC projects $45 net saved")
    trace.conclude(verdict="kill", confidence=0.8,
                   narrative="ROAS 0.9 < 1.5 threshold; sim + history agree")
    trace.persist()

Retrievable later:
    from core.brain.decision_trace import get_trace
    get_trace("dec_abc123")
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


_DB_PATH = Path("data/memory_intelligence.db")

EvidenceKind = Literal[
    "memory", "fact", "simulation", "skill",
    "rule", "feedback", "counterfactual", "narrative",
]


@dataclass
class Evidence:
    kind: EvidenceKind
    ref_id: str                # numeric id or "subject.predicate" for facts
    weight: float              # 0-1; share of decision influence
    note: str = ""
    ref: dict[str, Any] | None = None   # inline payload if no id

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ref_id": self.ref_id,
            "weight": round(self.weight, 3),
            "note": self.note,
            "ref": self.ref,
        }


@dataclass
class Trace:
    goal: str = ""
    id: str = ""
    created_at: float = 0.0
    concluded_at: float = 0.0
    verdict: str = ""
    confidence: float = 0.0
    narrative: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"dec_{uuid.uuid4().hex[:12]}"
        if not self.created_at:
            self.created_at = time.time()

    def cite(
        self,
        kind: EvidenceKind,
        ref_id: Any = "",
        weight: float = 0.1,
        note: str = "",
        ref: dict[str, Any] | None = None,
    ) -> Evidence:
        ev = Evidence(
            kind=kind,
            ref_id=str(ref_id),
            weight=max(0.0, min(1.0, float(weight))),
            note=str(note or "")[:400],
            ref=ref,
        )
        self.evidence.append(ev)
        return ev

    def conclude(
        self,
        verdict: str,
        confidence: float = 0.0,
        narrative: str = "",
    ) -> None:
        self.verdict = verdict
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.narrative = narrative
        self.concluded_at = time.time()

    def normalise_weights(self) -> None:
        """Rescale weights so they sum to 1. Evidence with zero weight
        is left untouched."""
        total = sum(e.weight for e in self.evidence)
        if total <= 0:
            return
        for e in self.evidence:
            e.weight = e.weight / total

    def top_evidence(self, k: int = 3) -> list[Evidence]:
        return sorted(self.evidence, key=lambda e: -e.weight)[:k]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "created_at": self.created_at,
            "concluded_at": self.concluded_at,
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "narrative": self.narrative,
            "evidence": [e.as_dict() for e in self.evidence],
            "metadata": self.metadata,
        }

    def persist(self) -> int | None:
        """Write the trace to MemoryIntelligence. Returns the new
        memory id, or ``None`` on failure (never raises)."""
        try:
            from core.memory.intelligence import get_memory_intelligence
            mi = get_memory_intelligence()
            mid = mi.create(
                category="decision_trace",
                content=self.as_dict(),
                action=self.verdict or "decide",
                score=3.0 + 2.0 * self.confidence,
                memory_type="semantic",
                tags=["decision_trace", "xai", self.id,
                      *(f"kind:{e.kind}" for e in self.evidence[:5])],
            )
            return int(mid) if mid else None
        except Exception:
            return None


# ── Retrieval ────────────────────────────────────────────────

def get_trace(trace_id: str) -> dict[str, Any] | None:
    """Fetch a persisted trace by its id tag."""
    if not _DB_PATH.exists() or not trace_id:
        return None
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories "
            "WHERE category='decision_trace' AND tags LIKE ? "
            "ORDER BY timestamp DESC LIMIT 1",
            (f"%{trace_id}%",),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    try:
        return json.loads(row[0] or "{}")
    except (json.JSONDecodeError, ValueError):
        return None


def recent(limit: int = 20) -> list[dict[str, Any]]:
    if not _DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM memories "
            "WHERE category='decision_trace' "
            "ORDER BY timestamp DESC LIMIT ?",
            (int(limit),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for (content,) in rows:
        try:
            out.append(json.loads(content or "{}"))
        except (json.JSONDecodeError, ValueError):
            continue
    return out


def explain(trace_id: str, top_k: int = 3) -> str:
    """Render a human-readable explanation of a past trace."""
    trace = get_trace(trace_id)
    if trace is None:
        return f"(no trace '{trace_id}')"
    lines = [
        f"Decision {trace_id}: {trace.get('verdict', '?')} "
        f"(confidence {trace.get('confidence', 0):.0%})",
        f"Goal: {trace.get('goal', '')}",
        f"Narrative: {trace.get('narrative', '(none)')}",
        "",
        f"Top evidence ({top_k}):",
    ]
    evidence = sorted(
        trace.get("evidence") or [],
        key=lambda e: -float(e.get("weight") or 0),
    )[:top_k]
    for e in evidence:
        lines.append(
            f"  [{e.get('kind', '?'):>12s}] ref={e.get('ref_id')!s:<20s} "
            f"w={float(e.get('weight') or 0):.2f}  {e.get('note', '')[:80]}"
        )
    return "\n".join(lines)
