"""Audit log — append-only immutable action log with hash chain.

Every money-moving action should leave an unforgeable record:
who did it, when, what, and with which inputs. Without it,
debugging a bad decision or answering compliance questions means
grepping stdout. An audit log is the professional answer.

AuditLog uses a hash chain (each entry hashes over the prior
entry's hash) so tampering is detectable: if anyone edits or
deletes a row, verify() returns False at that point.

APIs:

  append(actor, action, payload) → AuditEntry
  entries(limit, actor?, action?, since?) → list[AuditEntry]
  verify(from_seq=0) → VerifyReport (ok, broken_at?)
  latest() → AuditEntry or None
  stats()

Each entry carries:
  seq, ts, actor, action, payload_hash, prev_hash, entry_hash
Payload is stored separately so large blobs don't bloat the chain.

Persistence: ``data/audit_log.db`` SQLite. Append-only enforced
in code (no update/delete API). Thread-safe. Zero LLM.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


_DB_PATH = Path("data/audit_log.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    actor        TEXT NOT NULL,
    action       TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    entry_hash   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actor ON audit(actor);
CREATE INDEX IF NOT EXISTS idx_action ON audit(action);
"""


@dataclass
class AuditEntry:
    seq: int
    ts: float
    actor: str
    action: str
    payload: Any
    payload_hash: str
    prev_hash: str
    entry_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "actor": self.actor,
            "action": self.action,
            "payload": self.payload,
            "payload_hash": self.payload_hash,
            "prev_hash": self.prev_hash,
            "entry_hash": self.entry_hash,
        }


@dataclass
class VerifyReport:
    ok: bool
    checked: int = 0
    broken_at: int | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "broken_at": self.broken_at,
            "reason": self.reason,
        }


# ── Log ────────────────────────────────────────────────────

class AuditLog:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Append ─────────────────────────────────────────────

    def append(
        self, actor: str, action: str, payload: Any,
    ) -> AuditEntry:
        actor = (actor or "").strip()
        action = (action or "").strip()
        if not actor or not action:
            raise ValueError("actor and action required")
        payload_json = json.dumps(payload, sort_keys=True, default=str)
        payload_hash = _sha256(payload_json)
        ts = time.time()
        with self._lock, self._connect() as conn:
            prev_row = conn.execute(
                "SELECT entry_hash FROM audit ORDER BY seq DESC LIMIT 1",
            ).fetchone()
            prev_hash = prev_row[0] if prev_row else "genesis"
            # Leave seq to autoincrement; compute hash over the tuple
            # that *will* be assigned on insert.
            entry_hash = _sha256(
                f"{ts}|{actor}|{action}|{payload_hash}|{prev_hash}",
            )
            cur = conn.execute(
                "INSERT INTO audit "
                "(ts, actor, action, payload_json, "
                " payload_hash, prev_hash, entry_hash) "
                "VALUES (?,?,?,?,?,?,?)",
                (ts, actor, action, payload_json,
                 payload_hash, prev_hash, entry_hash),
            )
            conn.commit()
            seq = int(cur.lastrowid or 0)
        return AuditEntry(
            seq=seq, ts=ts, actor=actor, action=action,
            payload=payload,
            payload_hash=payload_hash,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )

    # ── Query ──────────────────────────────────────────────

    def entries(
        self,
        limit: int = 100,
        actor: str | None = None,
        action: str | None = None,
        since: float | None = None,
    ) -> list[AuditEntry]:
        clauses: list[str] = []
        params: list[Any] = []
        if actor:
            clauses.append("actor=?"); params.append(actor)
        if action:
            clauses.append("action=?"); params.append(action)
        if since is not None:
            clauses.append("ts >= ?"); params.append(float(since))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT seq, ts, actor, action, payload_json, "
                f"payload_hash, prev_hash, entry_hash "
                f"FROM audit{where} ORDER BY seq DESC LIMIT ?",
                (*params, int(limit)),
            ).fetchall()
        return [_row_to_entry(r) for r in rows]

    def latest(self) -> AuditEntry | None:
        items = self.entries(limit=1)
        return items[0] if items else None

    def get(self, seq: int) -> AuditEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT seq, ts, actor, action, payload_json, "
                "payload_hash, prev_hash, entry_hash "
                "FROM audit WHERE seq=?",
                (int(seq),),
            ).fetchone()
        return _row_to_entry(row) if row else None

    # ── Verify chain ───────────────────────────────────────

    def verify(self, from_seq: int = 0) -> VerifyReport:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, ts, actor, action, payload_json, "
                "payload_hash, prev_hash, entry_hash FROM audit "
                "WHERE seq >= ? ORDER BY seq ASC",
                (int(from_seq),),
            ).fetchall()
        report = VerifyReport(ok=True)
        prev_hash = None
        for row in rows:
            (seq, ts, actor, action, payload_json,
             payload_hash, stored_prev, stored_entry) = row
            report.checked += 1
            # 1. Payload hash matches body
            recomputed_ph = _sha256(payload_json)
            if recomputed_ph != payload_hash:
                report.ok = False
                report.broken_at = int(seq)
                report.reason = "payload hash mismatch"
                return report
            # 2. prev_hash matches previous entry's entry_hash
            if prev_hash is not None and stored_prev != prev_hash:
                report.ok = False
                report.broken_at = int(seq)
                report.reason = "prev_hash chain break"
                return report
            # 3. entry_hash matches recomputed
            recomputed_eh = _sha256(
                f"{ts}|{actor}|{action}|{payload_hash}|{stored_prev}",
            )
            if recomputed_eh != stored_entry:
                report.ok = False
                report.broken_at = int(seq)
                report.reason = "entry hash mismatch"
                return report
            prev_hash = stored_entry
        return report

    # ── Introspection ─────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM audit"
            ).fetchone()[0]
            by_actor = conn.execute(
                "SELECT actor, COUNT(*) FROM audit GROUP BY actor"
            ).fetchall()
            by_action = conn.execute(
                "SELECT action, COUNT(*) FROM audit GROUP BY action"
            ).fetchall()
        return {
            "total": int(total or 0),
            "by_actor": {a: int(c) for a, c in by_actor},
            "by_action": {a: int(c) for a, c in by_action},
        }


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _row_to_entry(row: tuple) -> AuditEntry:
    payload_json = row[4] or "null"
    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, ValueError):
        payload = None
    return AuditEntry(
        seq=int(row[0]),
        ts=float(row[1]),
        actor=row[2], action=row[3],
        payload=payload,
        payload_hash=row[5], prev_hash=row[6],
        entry_hash=row[7],
    )
