"""SelfModel — the AI's model of itself.

Answers the questions:
    What can I do?           → capabilities()
    How good am I at X?      → get_capability(X)
    Where am I strong/weak?  → strengths() / weaknesses()
    What don't I know?       → knowledge_gaps()
    How am I changing?       → history()
    Who am I (one-liner)?    → narrative()

This is NOT a hardcoded config file. Every assessment is driven by
real data from the system's own operation:

    controller cycle results  → per-phase latency + error rates
    MemoryIntelligence rules  → capability coverage per domain
    Experience tool_knowledge → tool success rates
    Failure analysis          → uncovered weaknesses

Each assessment is appended to an audit log so we can see exactly
why a capability score changed. The rolled-up view in `capabilities`
is a weighted average of the raw assessments, weighted by
evidence_count so a single lucky run doesn't overwhelm 100 measured
outcomes.

Confidence is a separate axis from score: a capability can have
a high score (0.9) with low confidence (0.3) when we've only
observed it twice, or a low score with high confidence when we've
seen it fail reliably.

Storage: SQLite via the existing migration framework. The schema
supports querying the assessment audit log for any capability.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from utils.logger import get_logger

logger = get_logger("cognitive.self_model")

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "self_model.db"

# Score bounds — everything stored as a float in [0.0, 1.0]
_SCORE_MIN = 0.0
_SCORE_MAX = 1.0

# Capability thresholds for narrative generation
_STRENGTH_THRESHOLD = 0.75   # score ≥ 0.75 and confidence ≥ 0.5
_WEAKNESS_THRESHOLD = 0.35   # score ≤ 0.35 and confidence ≥ 0.5
_GAP_CONFIDENCE = 0.4        # confidence < 0.4 = we don't know enough


def _v1_initial_schema(conn: sqlite3.Connection) -> None:
    """v1: capabilities roll-up + assessments audit + snapshots history."""
    conn.executescript("""
        -- Rolled-up view: one row per capability, updated incrementally
        CREATE TABLE IF NOT EXISTS capabilities (
            name            TEXT PRIMARY KEY,
            score           REAL NOT NULL DEFAULT 0.5,
            confidence      REAL NOT NULL DEFAULT 0.0,
            evidence_count  INTEGER NOT NULL DEFAULT 0,
            last_source     TEXT DEFAULT '',
            last_notes      TEXT DEFAULT '',
            first_seen      REAL NOT NULL,
            last_updated    REAL NOT NULL
        );

        -- Append-only audit log of every assessment that contributed
        -- to a capability's current score
        CREATE TABLE IF NOT EXISTS assessments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            capability      TEXT NOT NULL,
            score           REAL NOT NULL,
            evidence_count  INTEGER NOT NULL DEFAULT 1,
            source          TEXT DEFAULT '',
            notes           TEXT DEFAULT '',
            timestamp       REAL NOT NULL
        );

        -- Periodic full-state snapshots, used by history() + reflection
        CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            narrative       TEXT DEFAULT '',
            capability_count INTEGER DEFAULT 0,
            avg_score       REAL DEFAULT 0.0,
            avg_confidence  REAL DEFAULT 0.0,
            strengths_json  TEXT DEFAULT '[]',
            weaknesses_json TEXT DEFAULT '[]',
            gaps_json       TEXT DEFAULT '[]',
            timestamp       REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_assess_cap ON assessments(capability);
        CREATE INDEX IF NOT EXISTS idx_assess_ts ON assessments(timestamp);
        CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(timestamp);
    """)


_MIGRATIONS: list[tuple[int, str, Any]] = [
    (1, "initial schema", _v1_initial_schema),
]
_SCHEMA_VERSION = max(m[0] for m in _MIGRATIONS)


class SelfModel:
    """The AI's introspective model of its own capabilities."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._db_path = str(db_path or _DB_PATH)
        self._local = threading.local()
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "c") or self._local.c is None:
            self._local.c = sqlite3.connect(self._db_path, timeout=10)
            self._local.c.row_factory = sqlite3.Row
            self._local.c.execute("PRAGMA journal_mode=WAL")
        return self._local.c

    def _init_schema(self) -> None:
        from core.db.migrations import Migrator, register_schema
        Migrator(self._conn(), "self_model", _MIGRATIONS).run()
        register_schema("self_model", Path(self._db_path), _SCHEMA_VERSION)

    # ── Write API ──────────────────────────────────────────────

    def assess(
        self,
        capability: str,
        score: float,
        *,
        evidence_count: int = 1,
        source: str = "",
        notes: str = "",
    ) -> None:
        """Record a single assessment for a capability.

        The rolled-up capability score is updated as a weighted average:
            new_score = (old_score * old_evidence + score * evidence_count)
                        / (old_evidence + evidence_count)

        Confidence grows with total evidence via tanh so it saturates
        near 1.0 after ~10-20 observations and never reaches 1.0
        exactly (we're never 100% sure of anything).
        """
        if not capability:
            return
        score = max(_SCORE_MIN, min(_SCORE_MAX, float(score)))
        evidence_count = max(1, int(evidence_count))
        now = time.time()

        conn = self._conn()
        # Append to audit log
        conn.execute(
            "INSERT INTO assessments (capability, score, evidence_count, source, notes, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (capability, score, evidence_count, source, notes[:500], now),
        )

        # Update or insert the rolled-up capability
        existing = conn.execute(
            "SELECT score, evidence_count FROM capabilities WHERE name = ?",
            (capability,),
        ).fetchone()

        if existing:
            old_score = float(existing["score"])
            old_ev = int(existing["evidence_count"])
            total_ev = old_ev + evidence_count
            new_score = (old_score * old_ev + score * evidence_count) / total_ev
            new_confidence = self._confidence_from_evidence(total_ev)
            conn.execute(
                "UPDATE capabilities "
                "SET score = ?, confidence = ?, evidence_count = ?, "
                "    last_source = ?, last_notes = ?, last_updated = ? "
                "WHERE name = ?",
                (new_score, new_confidence, total_ev, source, notes[:500], now, capability),
            )
        else:
            conn.execute(
                "INSERT INTO capabilities "
                "(name, score, confidence, evidence_count, last_source, last_notes, first_seen, last_updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    capability, score,
                    self._confidence_from_evidence(evidence_count),
                    evidence_count, source, notes[:500], now, now,
                ),
            )
        conn.commit()

    def ingest_cycle_result(self, cycle_result: dict[str, Any]) -> int:
        """Extract capability signals from an autonomous-cycle result.

        The controller's cycle returns per-phase timings, execution
        results, and learning counts. We translate these into concrete
        capability assessments.

        Returns:
            The number of assessments written.
        """
        if not isinstance(cycle_result, dict):
            return 0

        written = 0
        phases = cycle_result.get("phases", {}) or {}
        executions = cycle_result.get("executions", []) or []

        # Phase latency health: each phase under 5s = strong
        for phase_name, phase_info in phases.items():
            if not isinstance(phase_info, dict):
                continue
            duration = phase_info.get("duration_s") or phase_info.get("elapsed", 0)
            if duration is None:
                continue
            try:
                d = float(duration)
            except (TypeError, ValueError):
                continue
            # Map latency to a 0-1 score: under 2s = 1.0, over 20s = 0.0
            score = max(0.0, min(1.0, 1.0 - (d - 2.0) / 18.0))
            self.assess(
                f"phase.{phase_name}",
                score,
                source="cycle",
                notes=f"duration={d:.2f}s",
            )
            written += 1

        # Execution success rate per engine
        engine_stats: dict[str, list[bool]] = {}
        for ex in executions:
            if not isinstance(ex, dict):
                continue
            engine = ex.get("engine") or ex.get("engine_name") or ex.get("name")
            status = ex.get("status") or (ex.get("result") or {}).get("status")
            if not engine:
                continue
            ok = status in ("success", "ok", "completed")
            engine_stats.setdefault(engine, []).append(ok)

        for engine, results in engine_stats.items():
            score = sum(results) / len(results)
            self.assess(
                f"engine.{engine}",
                score,
                evidence_count=len(results),
                source="cycle",
                notes=f"runs={len(results)}, ok={sum(results)}",
            )
            written += 1

        # Overall cycle outcome: did it complete?
        overall = cycle_result.get("status") or cycle_result.get("outcome")
        if overall in ("success", "completed", "ok"):
            self.assess("autonomy.cycle_completion", 1.0, source="cycle")
            written += 1
        elif overall in ("error", "fail", "failure"):
            error = cycle_result.get("error", "")
            self.assess(
                "autonomy.cycle_completion",
                0.0,
                source="cycle",
                notes=f"error={str(error)[:120]}",
            )
            written += 1

        return written

    def ingest_memory_stats(self, memory_intel: Any) -> int:
        """Derive capabilities from MemoryIntelligence rule coverage.

        Categories with many high-confidence rules indicate strong
        domain knowledge; categories with few or low-confidence rules
        are knowledge gaps.
        """
        if memory_intel is None:
            return 0
        try:
            rules = memory_intel.get_rules() or []
        except Exception:  # noqa: BLE001
            return 0

        # Group by category
        by_cat: dict[str, list[dict]] = {}
        for r in rules:
            cat = r.get("category") or "unknown"
            by_cat.setdefault(cat, []).append(r)

        written = 0
        for cat, cat_rules in by_cat.items():
            confidences = [float(r.get("confidence", 0.5) or 0.5) for r in cat_rules]
            avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
            self.assess(
                f"knowledge.{cat}",
                avg_conf,
                evidence_count=len(cat_rules),
                source="memory",
                notes=f"rules={len(cat_rules)}",
            )
            written += 1
        return written

    def snapshot(self) -> dict[str, Any]:
        """Capture the current self-model state into history."""
        caps = self.capabilities()
        strengths = self.strengths(top_n=5)
        weaknesses = self.weaknesses(top_n=5)
        gaps = self.knowledge_gaps(top_n=5)
        narrative = self.narrative()

        avg_score = (
            sum(c["score"] for c in caps) / len(caps) if caps else 0.0
        )
        avg_confidence = (
            sum(c["confidence"] for c in caps) / len(caps) if caps else 0.0
        )

        conn = self._conn()
        cur = conn.execute(
            "INSERT INTO snapshots "
            "(narrative, capability_count, avg_score, avg_confidence, "
            " strengths_json, weaknesses_json, gaps_json, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                narrative,
                len(caps),
                avg_score,
                avg_confidence,
                json.dumps(strengths),
                json.dumps(weaknesses),
                json.dumps(gaps),
                time.time(),
            ),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "narrative": narrative,
            "capability_count": len(caps),
            "avg_score": avg_score,
            "avg_confidence": avg_confidence,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "gaps": gaps,
        }

    # ── Read API ───────────────────────────────────────────────

    def get_capability(self, name: str) -> Optional[dict[str, Any]]:
        """Return the rolled-up assessment for one capability."""
        row = self._conn().execute(
            "SELECT * FROM capabilities WHERE name = ?", (name,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def capabilities(self) -> list[dict[str, Any]]:
        """Return every capability, ordered by score (high to low)."""
        rows = self._conn().execute(
            "SELECT * FROM capabilities ORDER BY score DESC, evidence_count DESC",
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def strengths(self, top_n: int = 5) -> list[dict[str, Any]]:
        """Top capabilities where score ≥ _STRENGTH_THRESHOLD and
        confidence ≥ 0.5."""
        rows = self._conn().execute(
            "SELECT * FROM capabilities "
            "WHERE score >= ? AND confidence >= 0.5 "
            "ORDER BY score DESC LIMIT ?",
            (_STRENGTH_THRESHOLD, top_n),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def weaknesses(self, top_n: int = 5) -> list[dict[str, Any]]:
        """Capabilities with score ≤ _WEAKNESS_THRESHOLD and confidence ≥ 0.5.

        We require confidence ≥ 0.5 so a single bad observation isn't
        reported as a weakness.
        """
        rows = self._conn().execute(
            "SELECT * FROM capabilities "
            "WHERE score <= ? AND confidence >= 0.5 "
            "ORDER BY score ASC LIMIT ?",
            (_WEAKNESS_THRESHOLD, top_n),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def knowledge_gaps(self, top_n: int = 5) -> list[dict[str, Any]]:
        """Capabilities where confidence < _GAP_CONFIDENCE.

        These are areas where the AI doesn't have enough data to know
        whether it's good or bad. Used by the curiosity module to pick
        exploration targets.
        """
        rows = self._conn().execute(
            "SELECT * FROM capabilities "
            "WHERE confidence < ? "
            "ORDER BY evidence_count ASC LIMIT ?",
            (_GAP_CONFIDENCE, top_n),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def confidence(self, capability: str) -> float:
        """Shortcut: confidence for one capability (0.0 if unknown)."""
        cap = self.get_capability(capability)
        return cap["confidence"] if cap else 0.0

    def assessment_log(
        self,
        capability: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return the audit trail — optionally filtered to one capability."""
        if capability:
            rows = self._conn().execute(
                "SELECT * FROM assessments WHERE capability = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (capability, limit),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM assessments ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return past snapshots (most recent first)."""
        rows = self._conn().execute(
            "SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for key in ("strengths_json", "weaknesses_json", "gaps_json"):
                if key in d:
                    try:
                        d[key.replace("_json", "")] = json.loads(d.pop(key) or "[]")
                    except json.JSONDecodeError:
                        d[key.replace("_json", "")] = []
            out.append(d)
        return out

    def narrative(self) -> str:
        """A one-paragraph human-readable self-description.

        Generated from current strengths, weaknesses, and gaps — not
        a template. Used by reflection and dashboards.
        """
        caps = self.capabilities()
        if not caps:
            return (
                "I have no data about myself yet. "
                "I'll learn who I am as I operate."
            )

        strong = self.strengths(top_n=3)
        weak = self.weaknesses(top_n=3)
        gaps = self.knowledge_gaps(top_n=3)

        parts: list[str] = []
        parts.append(
            f"I know of {len(caps)} capability(s) with "
            f"{sum(c['evidence_count'] for c in caps)} total observations."
        )

        if strong:
            names = ", ".join(c["name"] for c in strong)
            parts.append(f"My strengths are: {names}.")
        if weak:
            names = ", ".join(c["name"] for c in weak)
            parts.append(f"My weaknesses are: {names}.")
        if gaps:
            names = ", ".join(c["name"] for c in gaps)
            parts.append(f"I'm uncertain about: {names}.")

        return " ".join(parts)

    # ── Internal helpers ───────────────────────────────────────

    @staticmethod
    def _confidence_from_evidence(evidence_count: int) -> float:
        """Map evidence count → confidence in [0, ~0.99] via tanh.

        tanh(n/10): saturates ~0.99 at n=30, ~0.76 at n=10,
        ~0.46 at n=5, ~0.10 at n=1. Never quite reaches 1.0.
        """
        return math.tanh(max(0, evidence_count) / 10.0)

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "name": row["name"],
            "score": float(row["score"]),
            "confidence": float(row["confidence"]),
            "evidence_count": int(row["evidence_count"]),
            "last_source": row["last_source"] or "",
            "last_notes": row["last_notes"] or "",
            "first_seen": float(row["first_seen"]),
            "last_updated": float(row["last_updated"]),
        }


# ── Singleton accessor ─────────────────────────────────────────

_instance: Optional[SelfModel] = None


def get_self_model() -> SelfModel:
    """Return the process-wide SelfModel instance.

    Cached so the entire cognitive pipeline shares one view of
    self-knowledge.
    """
    global _instance
    if _instance is None:
        _instance = SelfModel()
    return _instance
