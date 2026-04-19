"""Reasoning trace — structured chain-of-evidence per decision.

decision_audit_trail walks the experience ledger *after* a decision
to reconstruct its context. reasoning_trace is proactive: while a
decision is being made, every subsystem that contributes an opinion
*writes* its contribution into the trace. At commit time, the trace
is a complete, ordered, machine-readable record of:

  • which subsystems were consulted
  • what each one produced
  • what weight the caller gave it
  • when it happened

Used by explanation_aggregator to produce owner-facing "why" notes
without guessing, and by self_revision_journal to learn from
patterns in past reasoning chains.

Pure stdlib, not persisted (trace lives for the duration of one
decision + the owner's followup). Thread-safe so concurrent brain
calls don't cross streams.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.reasoning_trace")


@dataclass
class TraceNode:
    subsystem: str
    note: str
    output: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    ts: float = 0.0

    def __post_init__(self) -> None:
        if not self.subsystem:
            raise ValueError("subsystem required")
        if self.weight < 0:
            raise ValueError("weight must be non-negative")
        if not self.ts:
            self.ts = time.time()

    def as_dict(self) -> dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "note": self.note,
            "output": dict(self.output),
            "weight": round(self.weight, 4),
            "ts": self.ts,
        }


@dataclass
class ReasoningTrace:
    trace_id: str
    question: str
    nodes: list[TraceNode] = field(default_factory=list)
    final_verdict: str = ""
    final_action: dict[str, Any] | None = None
    started_at: float = 0.0
    ended_at: float | None = None

    @property
    def duration_s(self) -> float:
        if not self.ended_at:
            return 0.0
        return max(0.0, self.ended_at - self.started_at)

    @property
    def subsystems_consulted(self) -> list[str]:
        return sorted({n.subsystem for n in self.nodes})

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "question": self.question,
            "nodes": [n.as_dict() for n in self.nodes],
            "final_verdict": self.final_verdict,
            "final_action": (
                dict(self.final_action)
                if self.final_action else None
            ),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_s": round(self.duration_s, 3),
            "subsystems_consulted": self.subsystems_consulted,
        }


class ReasoningTracer:
    """Per-process registry of live traces keyed by trace_id."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._traces: dict[str, ReasoningTrace] = {}

    # ── Lifecycle ────────────────────────────────────────

    def start(
        self, question: str,
        *, trace_id: str | None = None,
    ) -> str:
        if not question:
            raise ValueError("question required")
        tid = trace_id or uuid.uuid4().hex
        trace = ReasoningTrace(
            trace_id=tid,
            question=question,
            started_at=time.time(),
        )
        with self._lock:
            if tid in self._traces:
                raise ValueError(
                    f"trace {tid!r} already active",
                )
            self._traces[tid] = trace
        return tid

    def is_active(self, trace_id: str) -> bool:
        with self._lock:
            trace = self._traces.get(trace_id)
        return trace is not None and trace.ended_at is None

    def add(
        self,
        trace_id: str,
        *,
        subsystem: str,
        note: str,
        output: dict[str, Any] | None = None,
        weight: float = 1.0,
    ) -> None:
        node = TraceNode(
            subsystem=subsystem,
            note=note,
            output=dict(output or {}),
            weight=float(weight),
        )
        with self._lock:
            trace = self._traces.get(trace_id)
            if trace is None:
                raise ValueError(
                    f"unknown trace {trace_id!r}",
                )
            if trace.ended_at is not None:
                raise ValueError(
                    f"trace {trace_id!r} already ended",
                )
            trace.nodes.append(node)

    def commit(
        self,
        trace_id: str,
        *,
        verdict: str,
        action: dict[str, Any] | None = None,
    ) -> ReasoningTrace:
        with self._lock:
            trace = self._traces.get(trace_id)
            if trace is None:
                raise ValueError(
                    f"unknown trace {trace_id!r}",
                )
            trace.final_verdict = str(verdict)
            trace.final_action = (
                dict(action) if action else None
            )
            trace.ended_at = time.time()
            # Return a defensive copy so later edits don't mutate it
            return ReasoningTrace(
                trace_id=trace.trace_id,
                question=trace.question,
                nodes=list(trace.nodes),
                final_verdict=trace.final_verdict,
                final_action=(
                    dict(trace.final_action)
                    if trace.final_action else None
                ),
                started_at=trace.started_at,
                ended_at=trace.ended_at,
            )

    def abandon(self, trace_id: str) -> bool:
        """Drop an in-flight trace without committing (cancelled)."""
        with self._lock:
            return self._traces.pop(trace_id, None) is not None

    # ── Query ────────────────────────────────────────────

    def get(self, trace_id: str) -> ReasoningTrace | None:
        with self._lock:
            trace = self._traces.get(trace_id)
        if trace is None:
            return None
        # Defensive copy
        return ReasoningTrace(
            trace_id=trace.trace_id,
            question=trace.question,
            nodes=list(trace.nodes),
            final_verdict=trace.final_verdict,
            final_action=(
                dict(trace.final_action)
                if trace.final_action else None
            ),
            started_at=trace.started_at,
            ended_at=trace.ended_at,
        )

    def recent(
        self,
        *,
        limit: int = 20,
        committed_only: bool = True,
    ) -> list[ReasoningTrace]:
        with self._lock:
            traces = list(self._traces.values())
        if committed_only:
            traces = [t for t in traces if t.ended_at is not None]
        traces.sort(key=lambda t: -(t.ended_at or t.started_at))
        return traces[: max(1, int(limit))]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._traces)
            active = sum(
                1 for t in self._traces.values()
                if t.ended_at is None
            )
        return {
            "total": total,
            "active": active,
            "committed": total - active,
        }

    def clear(self) -> int:
        with self._lock:
            n = len(self._traces)
            self._traces.clear()
        return n
