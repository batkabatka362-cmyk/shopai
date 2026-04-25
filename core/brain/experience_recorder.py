"""Experience recorder — every cycle becomes learnable data.

Owner instruction: *"bas bvh hiigdsen ajilaa, vildel ajil, vnelgee bvree
data knowledge memory bolgoj hadgalj baiwal mash zuw"* — every action,
every evaluation, must be stored as data/knowledge/memory that the
brain can replay and learn from.

This module is the sink. It accepts structured events from three
feeders:

  1. Cycle phases     — ``record_phase(cycle_id, name, status, detail)``
  2. Decisions        — ``record_decision(ctx, chosen, alternatives)``
  3. LLM calls        — ``record_llm_call(prompt, result, learnable)``
  4. Outcomes         — ``record_outcome(action_id, kpi, value, source)``

Each event fans out to four sinks (each optional, each guarded):

  • SQLite ledger (always-on, durable)
  • ``case_based_reasoner`` (for decisions + outcomes)
  • ``learning_curve`` (for numeric KPIs)
  • Obsidian vault (for human-readable knowledge accumulation)

Pure stdlib orchestration. All sinks fail-soft.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.logger import get_logger


logger = get_logger("brain.experience_recorder")


_DB_PATH = Path("data/experience.db")
_OBSIDIAN_VAULT_ENV = "OBSIDIAN_VAULT_PATH"
_OBSIDIAN_DEFAULT = Path("vault")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS experiences (
    id         TEXT PRIMARY KEY,
    ts         REAL NOT NULL,
    kind       TEXT NOT NULL,
    cycle_id   TEXT,
    payload    TEXT NOT NULL,
    indexed    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_exp_cycle ON experiences(cycle_id, ts);
CREATE INDEX IF NOT EXISTS idx_exp_kind  ON experiences(kind, ts);
"""


@dataclass
class Experience:
    id: str
    ts: float
    kind: str
    cycle_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts,
            "kind": self.kind,
            "cycle_id": self.cycle_id,
            "payload": self.payload,
        }


_LOCK = threading.Lock()
_CONN: sqlite3.Connection | None = None


def _conn() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.commit()
        _CONN = conn
    return _CONN


# ── Internal write ────────────────────────────────────────

def _write(kind: str, cycle_id: str, payload: dict[str, Any]) -> Experience:
    eid = uuid.uuid4().hex
    now = time.time()
    with _LOCK:
        c = _conn()
        c.execute(
            "INSERT INTO experiences(id, ts, kind, cycle_id, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (eid, now, kind, cycle_id or "",
             json.dumps(payload, default=str, sort_keys=True)),
        )
        c.commit()
    return Experience(
        id=eid, ts=now, kind=kind,
        cycle_id=cycle_id or "", payload=payload,
    )


# ── Public record APIs ────────────────────────────────────

def record_phase(
    cycle_id: str,
    name: str,
    status: str,
    detail: dict[str, Any] | None = None,
) -> str:
    """Record a phase outcome from the autonomous cycle."""
    exp = _write(
        kind="phase",
        cycle_id=cycle_id,
        payload={
            "name": name, "status": status,
            "detail": detail or {},
        },
    )
    return exp.id


def record_decision(
    cycle_id: str,
    context: dict[str, Any],
    chosen: dict[str, Any] | None,
    alternatives: list[dict[str, Any]] | None = None,
    reasoning: str = "",
) -> str:
    """Record a decision the brain made."""
    exp = _write(
        kind="decision",
        cycle_id=cycle_id,
        payload={
            "context": context or {},
            "chosen": chosen or {},
            "alternatives": alternatives or [],
            "reasoning": reasoning,
        },
    )
    _fanout_to_case_base(context, chosen)
    _mirror_to_obsidian(
        title=f"Decision {exp.id[:8]}",
        body=_render_decision_md(context, chosen, alternatives, reasoning),
        folder="Decisions",
        frontmatter={
            "kind": "decision",
            "cycle_id": cycle_id,
            "ts": exp.ts,
        },
    )
    return exp.id


def record_llm_call(
    prompt: str,
    result: Any,
    learnable: bool = False,
) -> str:
    """Record an LLM call made through the gateway."""
    payload = {
        "prompt_len": len(prompt),
        "prompt_preview": prompt[:240],
        "ok": bool(getattr(result, "ok", False)),
        "adapter": str(getattr(result, "adapter", "") or ""),
        "model": str(getattr(result, "model", "") or ""),
        "cost_usd": float(getattr(result, "cost_usd", 0.0) or 0.0),
        "latency_ms": float(getattr(result, "latency_ms", 0.0) or 0.0),
        "tokens_in": int(getattr(result, "tokens_in", 0) or 0),
        "tokens_out": int(getattr(result, "tokens_out", 0) or 0),
        "purpose": str(getattr(result, "purpose", "") or ""),
        "error": str(getattr(result, "error", "") or ""),
    }
    exp = _write(
        kind="llm_call",
        cycle_id=os.environ.get("SHOPAI_CURRENT_CYCLE_ID", ""),
        payload=payload,
    )
    if learnable:
        _mirror_to_obsidian(
            title=f"LLM call {exp.id[:8]}",
            body=(
                f"## Prompt\n\n```\n{prompt[:2000]}\n```\n\n"
                f"## Result\n\n"
                f"- adapter: {payload['adapter']}\n"
                f"- model: {payload['model']}\n"
                f"- ok: {payload['ok']}\n"
                f"- cost: ${payload['cost_usd']:.6f}\n"
                f"- latency: {payload['latency_ms']:.1f}ms\n\n"
                f"## Output\n\n{str(getattr(result, 'text', ''))[:2000]}\n"
            ),
            folder="LLM",
            frontmatter={
                "kind": "llm_call",
                "adapter": payload["adapter"],
                "model": payload["model"],
                "ts": exp.ts,
            },
        )
    return exp.id


def record_outcome(
    action_id: str,
    kpi: str,
    value: float,
    *,
    source: str = "",
    cycle_id: str = "",
    features: dict[str, Any] | None = None,
) -> str:
    """Record an outcome event — the ground truth signal for learning."""
    exp = _write(
        kind="outcome",
        cycle_id=cycle_id,
        payload={
            "action_id": action_id,
            "kpi": kpi,
            "value": float(value),
            "source": source,
            "features": features or {},
        },
    )
    _fanout_to_learning_curve(kpi, float(value), cycle_id)
    return exp.id


def record_assessment(
    cycle_id: str,
    summary: str,
    health_score: float | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> str:
    """Record a self-assessment (reflection report, critic verdict)."""
    exp = _write(
        kind="assessment",
        cycle_id=cycle_id,
        payload={
            "summary": summary,
            "health_score": health_score,
            "findings": findings or [],
        },
    )
    _mirror_to_obsidian(
        title=f"Assessment {cycle_id[:8] if cycle_id else exp.id[:8]}",
        body=_render_assessment_md(summary, health_score, findings or []),
        folder="Assessments",
        frontmatter={
            "kind": "assessment",
            "cycle_id": cycle_id,
            "health_score": health_score,
            "ts": exp.ts,
        },
    )
    return exp.id


# ── Fan-out helpers (all fail-soft) ───────────────────────

def _fanout_to_case_base(
    context: dict[str, Any], chosen: dict[str, Any] | None,
) -> None:
    if not chosen:
        return
    action = str(chosen.get("action") or chosen.get("kind") or "")
    if not action:
        return
    score = float(
        chosen.get("outcome_score")
        or chosen.get("confidence")
        or 3.0,
    )
    try:
        from core.memory.case_based_reasoner import CaseBasedReasoner
        _case_base_singleton().add(
            situation=dict(context), action=action,
            outcome_score=score,
            tags=tuple(str(t) for t in chosen.get("tags", [])),
        )
    except Exception as exc:
        logger.debug("case_based fanout failed: %s", exc)


def _fanout_to_learning_curve(
    kpi: str, value: float, cycle_id: str,
) -> None:
    if not kpi:
        return
    try:
        _learning_tracker_singleton().record(
            subsystem="cycle", metric=kpi, value=value,
        )
    except Exception as exc:
        logger.debug("learning_curve fanout failed: %s", exc)


def _mirror_to_obsidian(
    title: str, body: str,
    folder: str = "",
    frontmatter: dict[str, Any] | None = None,
) -> None:
    """Best-effort Obsidian write. Silent when vault / pyyaml missing."""
    vault_path = Path(os.environ.get(_OBSIDIAN_VAULT_ENV, str(_OBSIDIAN_DEFAULT)))
    if not vault_path.exists():
        return
    try:
        from core.adapters.obsidian.parser import write_note
        write_note(
            vault_path=vault_path,
            title=title, body=body,
            frontmatter=frontmatter or {},
            folder=folder,
        )
    except Exception as exc:
        logger.debug("obsidian mirror failed: %s", exc)


# ── Singletons for fanout (DCLP) ─────────────────────────

_CASE_BASE: Any = None
_CASE_LOCK = threading.Lock()


def _case_base_singleton():
    global _CASE_BASE
    if _CASE_BASE is None:
        with _CASE_LOCK:
            if _CASE_BASE is None:
                from core.memory.case_based_reasoner import CaseBasedReasoner
                _CASE_BASE = CaseBasedReasoner()
    return _CASE_BASE


_LEARN_TRACKER: Any = None
_LEARN_LOCK = threading.Lock()


def _learning_tracker_singleton():
    global _LEARN_TRACKER
    if _LEARN_TRACKER is None:
        with _LEARN_LOCK:
            if _LEARN_TRACKER is None:
                from core.brain.learning_curve import LearningCurveTracker
                _LEARN_TRACKER = LearningCurveTracker()
    return _LEARN_TRACKER


# ── Renderers for Obsidian markdown ──────────────────────

def _render_decision_md(
    context: dict[str, Any],
    chosen: dict[str, Any] | None,
    alternatives: list[dict[str, Any]] | None,
    reasoning: str,
) -> str:
    lines = ["## Context"]
    for k, v in sorted((context or {}).items()):
        lines.append(f"- **{k}**: {v}")
    lines.append("\n## Chosen")
    if chosen:
        for k, v in sorted(chosen.items()):
            lines.append(f"- **{k}**: {v}")
    else:
        lines.append("- (no decision made)")
    if alternatives:
        lines.append("\n## Alternatives considered")
        for alt in alternatives[:5]:
            lines.append(f"- {alt}")
    if reasoning:
        lines.append("\n## Reasoning")
        lines.append(reasoning.strip())
    return "\n".join(lines)


def _render_assessment_md(
    summary: str,
    health_score: float | None,
    findings: list[dict[str, Any]],
) -> str:
    lines = [f"**Summary**: {summary.strip()}", ""]
    if health_score is not None:
        lines.append(f"**Health score**: {health_score}")
    if findings:
        lines.append("\n## Findings")
        for f in findings:
            lines.append(f"- {f}")
    return "\n".join(lines)


# ── Query API ────────────────────────────────────────────

def recent(
    cycle_id: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> list[Experience]:
    q = (
        "SELECT id, ts, kind, cycle_id, payload FROM experiences "
        "WHERE 1=1"
    )
    args: list[Any] = []
    if cycle_id:
        q += " AND cycle_id=?"
        args.append(cycle_id)
    if kind:
        q += " AND kind=?"
        args.append(kind)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(int(limit))
    with _LOCK:
        rows = _conn().execute(q, tuple(args)).fetchall()
    out: list[Experience] = []
    for r in rows:
        try:
            payload = json.loads(r[4])
        except (json.JSONDecodeError, ValueError):
            payload = {}
        out.append(Experience(
            id=r[0], ts=float(r[1]), kind=r[2],
            cycle_id=r[3] or "", payload=payload,
        ))
    return out


def stats() -> dict[str, Any]:
    with _LOCK:
        rows = _conn().execute(
            "SELECT kind, COUNT(*) FROM experiences GROUP BY kind",
        ).fetchall()
    counts = {k: int(n) for k, n in rows}
    return {
        "total": sum(counts.values()),
        "by_kind": counts,
    }
