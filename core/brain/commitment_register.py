"""Commitment register — durable promises with deadlines.

Brain makes commitments every cycle: 'reorder by Friday',
'reply within 24h', 'launch next Tuesday'. goal_agenda (v6-D1)
tracks big goals; commitment_register handles the smaller
time-bound promises that slip through the cracks otherwise.

Each Commitment carries:
  promise           — 1-sentence pledge
  owner             — who or what committed (brain, owner, customer)
  due_at            — unix ts deadline
  status            — open | fulfilled | defaulted | cancelled
  fulfillment_test  — optional callable that returns True when done

Commitments self-check on each tick: if due_at has passed and
fulfillment_test still returns False, status flips to defaulted.
Otherwise manual resolve() / cancel() / mark_fulfilled() move
them through the state machine.

APIs:

  register(promise, owner, due_at, test?) → Commitment
  tick(now?)                                → list of newly-defaulted
  mark_fulfilled(id) / cancel(id)
  pending / defaulted / fulfilled
  urgent(hours_ahead=24)

Persistence: ``data/commitments.db`` SQLite. Thread-safe, zero LLM.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal


Status = Literal["open", "fulfilled", "defaulted", "cancelled"]

_DB_PATH = Path("data/commitments.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS commitments (
    id           TEXT PRIMARY KEY,
    created_at   REAL NOT NULL,
    owner        TEXT NOT NULL,
    promise      TEXT NOT NULL,
    due_at       REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open',
    resolved_at  REAL,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS idx_status_due
    ON commitments(status, due_at);
CREATE INDEX IF NOT EXISTS idx_owner ON commitments(owner);
"""


@dataclass
class Commitment:
    id: str
    created_at: float
    owner: str
    promise: str
    due_at: float
    status: Status
    resolved_at: float | None = None
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "owner": self.owner,
            "promise": self.promise,
            "due_at": self.due_at,
            "status": self.status,
            "resolved_at": self.resolved_at,
            "note": self.note,
        }

    def hours_until_due(self, now: float | None = None) -> float:
        now = now or time.time()
        return (self.due_at - now) / 3600.0


FulfillmentTest = Callable[[], bool]


# ── Register ───────────────────────────────────────────────

class CommitmentRegister:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db = Path(db_path) if db_path else _DB_PATH
        self._tests: dict[str, FulfillmentTest] = {}
        self._lock = threading.Lock()
        self._db.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── Register ───────────────────────────────────────────

    def register(
        self,
        promise: str,
        owner: str,
        due_at: float,
        fulfillment_test: FulfillmentTest | None = None,
    ) -> Commitment:
        promise = promise.strip()
        owner = owner.strip()
        if not promise or not owner:
            raise ValueError("promise + owner required")
        if due_at <= 0:
            raise ValueError("due_at must be > 0")
        cid = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO commitments "
                "(id, created_at, owner, promise, due_at, status) "
                "VALUES (?,?,?,?,?, 'open')",
                (cid, now, owner, promise, float(due_at)),
            )
            conn.commit()
        if fulfillment_test is not None:
            self._tests[cid] = fulfillment_test
        return Commitment(
            id=cid, created_at=now, owner=owner,
            promise=promise, due_at=float(due_at),
            status="open",
        )

    # ── Tick + state transitions ──────────────────────────

    def tick(self, now: float | None = None) -> list[Commitment]:
        """Walk every open commitment. Fulfilled tests resolve;
        overdue items without a passing test default. Returns the
        list of commitments that *just* defaulted this tick."""
        now = now or time.time()
        newly_defaulted: list[Commitment] = []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM commitments WHERE status='open'",
            ).fetchall()
        for (cid,) in rows:
            test = self._tests.get(cid)
            fulfilled = False
            if test is not None:
                try:
                    fulfilled = bool(test())
                except Exception:
                    fulfilled = False
            if fulfilled:
                self._set_status(cid, "fulfilled", now)
                continue
            c = self._get(cid)
            if c and c.due_at < now:
                self._set_status(cid, "defaulted", now)
                updated = self._get(cid)
                if updated:
                    newly_defaulted.append(updated)
        return newly_defaulted

    def mark_fulfilled(
        self, commitment_id: str, note: str = "",
    ) -> bool:
        return self._set_status(
            commitment_id, "fulfilled",
            time.time(), note=note,
        )

    def cancel(
        self, commitment_id: str, reason: str = "",
    ) -> bool:
        return self._set_status(
            commitment_id, "cancelled",
            time.time(), note=reason,
        )

    # ── Queries ────────────────────────────────────────────

    def pending(
        self, owner: str | None = None, limit: int = 50,
    ) -> list[Commitment]:
        return self._by_status(
            "open", owner=owner, limit=limit,
            order="due_at ASC",
        )

    def defaulted(self, limit: int = 50) -> list[Commitment]:
        return self._by_status(
            "defaulted", limit=limit, order="resolved_at DESC",
        )

    def fulfilled(self, limit: int = 50) -> list[Commitment]:
        return self._by_status(
            "fulfilled", limit=limit, order="resolved_at DESC",
        )

    def urgent(self, hours_ahead: float = 24.0) -> list[Commitment]:
        """Open commitments due within the next N hours, soonest first."""
        cutoff = time.time() + hours_ahead * 3600.0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, created_at, owner, promise, due_at, "
                "status, resolved_at, note "
                "FROM commitments WHERE status='open' AND due_at <= ? "
                "ORDER BY due_at ASC",
                (cutoff,),
            ).fetchall()
        return [_row_to_commitment(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            counts = conn.execute(
                "SELECT status, COUNT(*) FROM commitments GROUP BY status"
            ).fetchall()
        out = {s: int(c) for s, c in counts}
        return {
            "counts": out,
            "total": sum(out.values()),
        }

    # ── Internals ──────────────────────────────────────────

    def _set_status(
        self, commitment_id: str, status: Status,
        resolved_at: float | None, note: str = "",
    ) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE commitments SET status=?, resolved_at=?, "
                "note = COALESCE(?, note) WHERE id=? AND status='open'",
                (status, resolved_at, note or None, commitment_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def _get(self, commitment_id: str) -> Commitment | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, created_at, owner, promise, due_at, "
                "status, resolved_at, note "
                "FROM commitments WHERE id=?",
                (commitment_id,),
            ).fetchone()
        return _row_to_commitment(row) if row else None

    def get(self, commitment_id: str) -> Commitment | None:
        return self._get(commitment_id)

    def _by_status(
        self, status: Status, *,
        owner: str | None = None,
        limit: int = 50, order: str = "due_at ASC",
    ) -> list[Commitment]:
        clauses = ["status=?"]
        params: list[Any] = [status]
        if owner:
            clauses.append("owner=?"); params.append(owner)
        where = " WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id, created_at, owner, promise, due_at, "
                f"status, resolved_at, note "
                f"FROM commitments{where} ORDER BY {order} LIMIT ?",
                (*params, int(limit)),
            ).fetchall()
        return [_row_to_commitment(r) for r in rows]


def _row_to_commitment(row: tuple) -> Commitment:
    return Commitment(
        id=row[0],
        created_at=float(row[1]),
        owner=row[2],
        promise=row[3],
        due_at=float(row[4]),
        status=row[5],
        resolved_at=row[6],
        note=row[7] or "",
    )
