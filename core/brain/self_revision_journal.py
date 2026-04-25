"""Self-revision journal — the brain edits its own rules / notes.

After every week the brain has three kinds of learnings:

  • wins          — decisions where outcome beat expectations
  • surprises     — unexpected outcomes (both good and bad)
  • lessons       — explicit rules added/modified/removed

Today these sit scattered across experience_recorder, learning_curve,
competence_model, and Obsidian notes. self_revision_journal is a
first-class journal where each entry is a *proposed revision* to
either:

  • a stored rule (e.g. "kill at ROAS < 1.5" → "at ROAS < 1.3")
  • a skill precondition
  • a knob value
  • a narrative/identity line

Each entry tracks:

  • id, kind, target (what rule/skill/knob this edits)
  • old_value, new_value
  • reason (human-readable)
  • status: proposed / accepted / rejected / applied
  • evidence_score (0..1 — how much evidence backs the change)

Owners (or an automated loop) can walk pending proposals and approve
them. Applied entries are audit-tracked.

SQLite-persisted, pure stdlib, deterministic.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from utils.logger import get_logger


logger = get_logger("brain.self_revision_journal")


Kind = Literal["rule", "skill", "knob", "narrative"]
Status = Literal["proposed", "accepted", "rejected", "applied"]


@dataclass
class Revision:
    id: str
    kind: Kind
    target: str
    old_value: Any
    new_value: Any
    reason: str
    evidence_score: float
    status: Status
    ts: float
    resolved_ts: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("rule", "skill", "knob", "narrative"):
            raise ValueError("kind must be rule|skill|knob|narrative")
        if self.status not in (
            "proposed", "accepted", "rejected", "applied",
        ):
            raise ValueError(
                "status must be proposed|accepted|rejected|applied",
            )
        if not 0 <= self.evidence_score <= 1:
            raise ValueError("evidence_score must be 0..1")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "target": self.target,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "reason": self.reason,
            "evidence_score": round(self.evidence_score, 4),
            "status": self.status,
            "ts": self.ts,
            "resolved_ts": self.resolved_ts,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS revisions (
    id             TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    target         TEXT NOT NULL,
    old_value      TEXT NOT NULL,
    new_value      TEXT NOT NULL,
    reason         TEXT NOT NULL,
    evidence_score REAL NOT NULL,
    status         TEXT NOT NULL,
    ts             REAL NOT NULL,
    resolved_ts    REAL
);
CREATE INDEX IF NOT EXISTS idx_rev_status
    ON revisions(status);
CREATE INDEX IF NOT EXISTS idx_rev_target
    ON revisions(kind, target);
"""


class SelfRevisionJournal:
    def __init__(
        self, db_path: str | Path | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, Revision] = {}
        self._conn: sqlite3.Connection | None = None
        if db_path is not None:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(path), check_same_thread=False,
            )
            with self._lock:
                self._conn.execute("PRAGMA busy_timeout=5000")
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.executescript(_SCHEMA)
                self._conn.commit()
            self._load()

    def _load(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            for row in self._conn.execute(
                "SELECT id, kind, target, old_value, new_value, "
                "reason, evidence_score, status, ts, resolved_ts "
                "FROM revisions",
            ):
                try:
                    old = json.loads(row[3])
                    new = json.loads(row[4])
                except (json.JSONDecodeError, ValueError):
                    continue
                self._entries[row[0]] = Revision(
                    id=row[0],
                    kind=row[1],
                    target=row[2],
                    old_value=old,
                    new_value=new,
                    reason=row[5],
                    evidence_score=float(row[6]),
                    status=row[7],
                    ts=float(row[8]),
                    resolved_ts=(
                        float(row[9]) if row[9] is not None else None
                    ),
                )

    def _persist(self, rev: Revision) -> None:
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO revisions("
            "  id, kind, target, old_value, new_value, "
            "  reason, evidence_score, status, ts, resolved_ts"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rev.id, rev.kind, rev.target,
                json.dumps(rev.old_value, default=str),
                json.dumps(rev.new_value, default=str),
                rev.reason,
                rev.evidence_score,
                rev.status,
                rev.ts,
                rev.resolved_ts,
            ),
        )
        self._conn.commit()

    # ── Propose ──────────────────────────────────────────

    def propose(
        self,
        *,
        kind: Kind,
        target: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        evidence_score: float = 0.5,
    ) -> Revision:
        if not target:
            raise ValueError("target required")
        if not reason:
            raise ValueError("reason required")
        rev = Revision(
            id=uuid.uuid4().hex,
            kind=kind,
            target=target,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            evidence_score=float(evidence_score),
            status="proposed",
            ts=time.time(),
        )
        with self._lock:
            self._entries[rev.id] = rev
            self._persist(rev)
        return rev

    # ── State transitions ────────────────────────────────

    def _transition(
        self, revision_id: str, new_status: Status,
    ) -> Revision:
        with self._lock:
            rev = self._entries.get(revision_id)
            if rev is None:
                raise ValueError(
                    f"unknown revision {revision_id!r}",
                )
            rev.status = new_status
            rev.resolved_ts = time.time()
            self._persist(rev)
            return rev

    def accept(self, revision_id: str) -> Revision:
        return self._transition(revision_id, "accepted")

    def reject(self, revision_id: str) -> Revision:
        return self._transition(revision_id, "rejected")

    def mark_applied(self, revision_id: str) -> Revision:
        return self._transition(revision_id, "applied")

    # ── Queries ──────────────────────────────────────────

    def get(self, revision_id: str) -> Revision | None:
        with self._lock:
            return self._entries.get(revision_id)

    def by_status(
        self, status: Status,
    ) -> list[Revision]:
        with self._lock:
            out = [
                r for r in self._entries.values()
                if r.status == status
            ]
        out.sort(key=lambda r: -r.ts)
        return out

    def by_target(
        self, target: str, *, kind: Kind | None = None,
    ) -> list[Revision]:
        with self._lock:
            out = [
                r for r in self._entries.values()
                if r.target == target
                and (kind is None or r.kind == kind)
            ]
        out.sort(key=lambda r: -r.ts)
        return out

    def recent(
        self, *, limit: int = 20,
    ) -> list[Revision]:
        with self._lock:
            rs = list(self._entries.values())
        rs.sort(key=lambda r: -r.ts)
        return rs[: max(1, int(limit))]

    # ── Stats ────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts: dict[str, int] = {}
            for r in self._entries.values():
                counts[r.status] = counts.get(r.status, 0) + 1
            return {
                "total": len(self._entries),
                "by_status": counts,
            }

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
